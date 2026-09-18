/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim4;
TIM_HandleTypeDef htim9;
TIM_HandleTypeDef htim12;

I2C_HandleTypeDef hi2c2;

UART_HandleTypeDef huart3;

/* USER CODE BEGIN PV */
uint8_t rx_byte;

uint8_t rx_buf[32];		// stores command typed
uint8_t rx_index = 0;

// Test Communication
uint8_t pong[] = "PONG\r\n";
uint8_t err_unknown[] = "ERR,UNKNOWN\r\n";

// Test Motor
uint8_t ack_f[] = "ACK,F\r\n";	// Forward
uint8_t ack_b[] = "ACK,B\r\n";	// Backward
uint8_t ack_s[] = "ACK,S\r\n";	// Stop (only stop verb — STOP removed)

// Motor speed (PWM). Fixed for now -- change MOTOR_SPEED_PCT and reflash to
// try a different speed. 0 = off, 100 = full power.
// PWM_MAX_DUTY matches the Counter Period CubeMX generated for TIM4/TIM9
// (65535, i.e. 16-bit resolution) -- don't change this unless you also
// change the Period in CubeMX.
#define PWM_MAX_DUTY 65535
#define MOTOR_SPEED_PCT 50
#define MOTOR_DUTY ((uint32_t)PWM_MAX_DUTY * MOTOR_SPEED_PCT / 100)

// Confirmed wiring: MotorA = RIGHT side, MotorB = LEFT side.
// Timed F/B duration (ms). Keep as short jog; use FW <cm> for distance.
#define MOVE_DURATION_MS 500

// FW/BW distance (RPi Task 1: 5–200 cm). Cal was A.3 band 80–120 — short/long may need retune.
#define COUNTS_PER_100CM 6185
#define FW_CM_MIN 5
#define FW_CM_MAX 200
#define FW_TIMEOUT_MS 60000
#define FW_BRAKE_MS 250		// hold AT8236 brake (IN1=IN2=high) after distance target
#define FW_BRAKE_DUTY PWM_MAX_DUTY

// FS = slow distance drive (Task 13). Same range/brake as FW; lower duty; own cal.
#define FS_SPEED_PCT 20
#define FS_DUTY ((uint32_t)PWM_MAX_DUTY * FS_SPEED_PCT / 100)
#define COUNTS_PER_100CM_FS 7182	// FS 80/100/120 @7110 → 80/99/118; minimax 7110×100/99

// PL/PR = gyro Z closed-loop pivot (Task 15C). No auto-SC.
// Hand-cal: left turn → Z+, right → Z−.
// Task 17: role-based duties — forward wheel stronger than reverse (60:40 of total).
#define PIVOT_FWD_PCT 42
#define PIVOT_REV_PCT 28
#define PIVOT_DUTY_FWD ((uint32_t)PWM_MAX_DUTY * PIVOT_FWD_PCT / 100)
#define PIVOT_DUTY_REV ((uint32_t)PWM_MAX_DUTY * PIVOT_REV_PCT / 100)
#define PIVOT_DEG_MIN 90
#define PIVOT_DEG_MAX 360
#define PIVOT_LEFT 1
#define PIVOT_RIGHT 2
#define PIVOT_BIAS_SAMPLES 40
#define PIVOT_BIAS_DT_MS 5
#define PIVOT_TIMEOUT_MS_PER_90 8000	/* failsafe only; stop is gyro-based */
#define PIVOT_STOP_MARGIN_DEG 3.0f	/* brake early to reduce overshoot */

// ICM-20948 on I2C2 (PB10=SCL, PB11=SDA), 7-bit addr 0x68 → HAL 8-bit 0xD0
#define ICM20948_ADDR_8BIT  0xD0
#define ICM20948_REG_BANK_SEL 0x7F
#define ICM20948_REG_WHO_AM_I 0x00
#define ICM20948_WHO_AM_I_VAL 0xEA
#define ICM20948_REG_PWR_MGMT_1 0x06
#define ICM20948_REG_PWR_MGMT_2 0x07
#define ICM20948_REG_LP_CONFIG 0x05
#define ICM20948_REG_ACCEL_XOUT_H 0x2D
#define ICM20948_REG_GYRO_XOUT_H 0x33
#define ICM20948_REG_GYRO_SMPLRT_DIV 0x00	/* user bank 2 */
#define ICM20948_REG_GYRO_CONFIG_1 0x01	/* user bank 2 */
#define ICM20948_GYRO_DPS_PER_LSB_X100 1640	/* ±2000 dps → 16.40 LSB/°/s * 100 */

// F/B, TL/TR, FW/FS, PL/PR run blocking work in the main loop (not inside the UART ISR).
volatile uint8_t pending_move = 0;	// 0 = none
#define MOVE_FORWARD 1
#define MOVE_BACKWARD 2

/* Gyro Ackermann arcs (Task 16): TL/TR forward, BL/BR reverse; LL/RR steer; 20%. */
volatile uint8_t pending_arc = 0;	// 0 = none
volatile uint16_t pending_arc_deg = 0;
#define ARC_TL 1
#define ARC_TR 2
#define ARC_BL 3
#define ARC_BR 4
#define TURN_ARC_SPEED_PCT 20
#define TURN_ARC_DUTY ((uint32_t)PWM_MAX_DUTY * TURN_ARC_SPEED_PCT / 100)
#define TURN_SERVO_SETTLE_MS 200
#define ARC_DEG_MIN 45
#define ARC_DEG_MAX 360
#define ARC_BIAS_SAMPLES 40
#define ARC_BIAS_DT_MS 5
#define ARC_TIMEOUT_MS_PER_90 8000
/* Task 18: overshoot grew with angle (~1.4%); stop early by percent, not fixed °. */
#define ARC_STOP_EARLY_PCT 1.4f

volatile uint16_t pending_fw_cm = 0;	// 0 = none; else FW distance cm
volatile uint16_t pending_bw_cm = 0;	// 0 = none; else BW distance cm
volatile uint16_t pending_fs_cm = 0;	// 0 = none; else FS distance cm
volatile uint16_t pending_bs_cm = 0;	// 0 = none; else BS distance cm
volatile uint8_t pending_pivot = 0;	// 0 = none; else PIVOT_LEFT / PIVOT_RIGHT
volatile uint16_t pending_pivot_deg = 0;
volatile uint8_t pending_imu = 0;	// 1 = run IMU whoami in main loop
volatile uint8_t pending_gyro = 0;	// 1 = run GYRO sample in main loop
volatile uint8_t drive_abort = 0;	// set by S to stop an in-progress drive/pivot/arc

uint8_t err_range[] = "ERR,RANGE\r\n";
uint8_t ack_fw[] = "ACK,FW\r\n";
uint8_t ack_bw[] = "ACK,BW\r\n";
uint8_t ack_fs[] = "ACK,FS\r\n";
uint8_t ack_bs[] = "ACK,BS\r\n";
uint8_t ack_pl[] = "ACK,PL\r\n";
uint8_t ack_pr[] = "ACK,PR\r\n";
uint8_t ack_tl[] = "ACK,TL\r\n";
uint8_t ack_tr[] = "ACK,TR\r\n";
uint8_t ack_bl[] = "ACK,BL\r\n";
uint8_t ack_br[] = "ACK,BR\r\n";
uint8_t done_fw[] = "DONE,FW\r\n";
uint8_t done_bw[] = "DONE,BW\r\n";
uint8_t done_fs[] = "DONE,FS\r\n";
uint8_t done_bs[] = "DONE,BS\r\n";
uint8_t done_pl[] = "DONE,PL\r\n";
uint8_t done_pr[] = "DONE,PR\r\n";
uint8_t done_tl[] = "DONE,TL\r\n";
uint8_t done_tr[] = "DONE,TR\r\n";
uint8_t done_bl[] = "DONE,BL\r\n";
uint8_t done_br[] = "DONE,BR\r\n";

#define MOTION_IDLE() \
  (pending_move == 0 && pending_arc == 0 && pending_fw_cm == 0 && \
   pending_fs_cm == 0 && pending_bs_cm == 0 && pending_bw_cm == 0 && \
   pending_pivot == 0)

// --- Front-wheel steering (servo, TIM12_CH2 / PB15) ---
// This chassis is Ackermann: prefer SC/SL/SR + F/FW or TL/TR for mission arcs.
// PL/PR = intentional on-spot differential pivot (rear wheels opposite); scrubs fronts.
// Do not reuse FL/FR for steer lock (those names were the old skid API).
// TL/TR/BL/BR = gyro Ackermann arcs (LL/RR + 20% drive); PL/PR = on-spot pivot.
// Standard RC servo: pulse width in microseconds (1 tick = 1 us after TIM12 fix).
// 1000-2000 is full typical RC range -- watch for buzz/bind at LL/RR after flash.
volatile uint32_t servo_pulse_us = 1500;	// current commanded pulse (updated by SL/SR/LL/RR)
#define SERVO_CENTER_US 1500
#define SERVO_STEP_US 100		// SL/SR nudge per command
#define SERVO_MIN_US 1000		// soft floor -- tighten if servo buzzes/binds
#define SERVO_MAX_US 2000		// soft ceiling -- tighten if servo buzzes/binds
uint8_t ack_sc[] = "ACK,SC\r\n";	// Steer center
uint8_t ack_sl[] = "ACK,SL\r\n";	// Steer step left
uint8_t ack_sr[] = "ACK,SR\r\n";	// Steer step right
uint8_t ack_ll[] = "ACK,LL\r\n";	// Steer lock at SERVO_MIN_US (intended left -- verify)
uint8_t ack_rr[] = "ACK,RR\r\n";	// Steer lock at SERVO_MAX_US (intended right -- verify)

// Wheel encoders (Task 12): schematic maps MotorA→PA15/PB3, MotorB→PB4/PB5.
// (PA0/PA1 are MotorD — unused on this 2WD car; that is why ENC stayed 0.)
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART3_UART_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM9_Init(void);
static void MX_TIM12_Init(void);
/* USER CODE BEGIN PFP */
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_I2C2_Init(void);
int ICM20948_WhoAmI(uint8_t *id_out);
int ICM20948_Init(void);
int ICM20948_ReadGyroRaw(int16_t *gx, int16_t *gy, int16_t *gz);
int ICM20948_ReadAccelRaw(int16_t *ax, int16_t *ay, int16_t *az);
int ICM20948_ReadGyroDps(int16_t *gx_dps, int16_t *gy_dps, int16_t *gz_dps);
void Imu_Report(void);
void Gyro_Report(void);
int16_t EncoderA_GetCount(void);
int16_t EncoderB_GetCount(void);
void Encoder_Reset(void);
uint32_t Encoder_DistCounts(void);

void Motors_Stop(void);

void MotorA_Stop(void);
void MotorA_Forward(uint32_t duty);
void MotorA_Backward(uint32_t duty);

void MotorB_Stop(void);
void MotorB_Forward(uint32_t duty);
void MotorB_Backward(uint32_t duty);

void Motors_Forward(void);
void Motors_Backward(void);
void Arc_Run(uint8_t arc_kind, uint16_t deg);
void Drive_ForwardCm(uint16_t cm);
void Drive_BackwardCm(uint16_t cm);
void Drive_ForwardSlowCm(uint16_t cm);
void Drive_BackwardSlowCm(uint16_t cm);
void Pivot_Run(uint8_t pivot_dir, uint16_t deg);

void Steer_SetPulse(uint32_t us);
void Steer_Center(void);
void Steer_StepLeft(void);
void Steer_StepRight(void);
void Steer_LockLeft(void);
void Steer_LockRight(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  //uint8_t sbuf[15] = "Hello World!\n\r";
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART3_UART_Init();
  MX_TIM4_Init();
  MX_TIM9_Init();
  MX_TIM12_Init();
  /* USER CODE BEGIN 2 */
  MX_TIM2_Init();	// Motor A encoder PA15/PB3
  MX_TIM3_Init();	// Motor B encoder PB4/PB5
  MX_I2C2_Init();	// ICM-20948 (PB10/PB11)
  HAL_TIM_Encoder_Start(&htim2, TIM_CHANNEL_ALL);
  HAL_TIM_Encoder_Start(&htim3, TIM_CHANNEL_ALL);
  Encoder_Reset();

  // Start the PWM signal on all 4 motor channels. They start at 0% duty
  // (see the ConfigChannel calls in MX_TIM4_Init/MX_TIM9_Init, Pulse = 0),
  // so nothing moves yet -- Motors_Stop() below also explicitly zeroes them.
  HAL_TIM_PWM_Start(&htim4, TIM_CHANNEL_3);	// MotorA IN2 (PB8)
  HAL_TIM_PWM_Start(&htim4, TIM_CHANNEL_4);	// MotorA IN1 (PB9)
  HAL_TIM_PWM_Start(&htim9, TIM_CHANNEL_1);	// MotorB IN1 (PE5)
  HAL_TIM_PWM_Start(&htim9, TIM_CHANNEL_2);	// MotorB IN2 (PE6)

  // Start the steering servo PWM and center it immediately -- do this before
  // anything else can move, so the servo doesn't sit at an unknown/random
  // position on power-up.
  HAL_TIM_PWM_Start(&htim12, TIM_CHANNEL_2);	// Steering servo (PB15)
  Steer_Center();

  Motors_Stop();
  /* Bring up UART before IMU init so CoolTerm still works if I2C stalls. */
  HAL_UART_Receive_IT(&huart3, &rx_byte, 1);
  (void)ICM20948_Init();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
	  // Process motion/turn flags before any long LED delay so CoolTerm
	  // commands are not stuck behind 2×1 s blinks.
	  if (pending_move != 0)
	  {
		  uint8_t move_to_run = pending_move;
		  pending_move = 0;

		  switch (move_to_run)
		  {
		    case MOVE_FORWARD:  Motors_Forward();  break;
		    case MOVE_BACKWARD: Motors_Backward(); break;
		  }
	  }

	  if (pending_arc != 0)
	  {
		  uint8_t kind = pending_arc;
		  uint16_t deg = pending_arc_deg;
		  pending_arc = 0;
		  pending_arc_deg = 0;
		  Arc_Run(kind, deg);
	  }

	  if (pending_fw_cm != 0)
	  {
		  uint16_t cm = pending_fw_cm;
		  pending_fw_cm = 0;
		  Drive_ForwardCm(cm);
	  }

	  if (pending_bw_cm != 0)
	  {
		  uint16_t cm = pending_bw_cm;
		  pending_bw_cm = 0;
		  Drive_BackwardCm(cm);
	  }

	  if (pending_fs_cm != 0)
	  {
		  uint16_t cm = pending_fs_cm;
		  pending_fs_cm = 0;
		  Drive_ForwardSlowCm(cm);
	  }

	  if (pending_bs_cm != 0)
	  {
		  uint16_t cm = pending_bs_cm;
		  pending_bs_cm = 0;
		  Drive_BackwardSlowCm(cm);
	  }

	  if (pending_pivot != 0)
	  {
		  uint8_t dir = pending_pivot;
		  uint16_t deg = pending_pivot_deg;
		  pending_pivot = 0;
		  pending_pivot_deg = 0;
		  Pivot_Run(dir, deg);
	  }

	  if (pending_imu)
	  {
		  pending_imu = 0;
		  Imu_Report();
	  }

	  if (pending_gyro)
	  {
		  pending_gyro = 0;
		  Gyro_Report();
	  }

	  // Slow heartbeat only when idle
	  if (MOTION_IDLE() && pending_imu == 0 && pending_gyro == 0)
	  {
		  HAL_GPIO_TogglePin(LED3_GPIO_Port, LED3_Pin);
		  HAL_Delay(200);
	  }
  }
  /* USER CODE END 3 *////
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM4_Init(void)
{

  /* USER CODE BEGIN TIM4_Init 0 */

  /* USER CODE END TIM4_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM4_Init 1 */

  /* USER CODE END TIM4_Init 1 */
  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 0;
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 65535;
  htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim4) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM4_Init 2 */

  /* USER CODE END TIM4_Init 2 */
  HAL_TIM_MspPostInit(&htim4);

}

/**
  * @brief TIM9 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM9_Init(void)
{

  /* USER CODE BEGIN TIM9_Init 0 */

  /* USER CODE END TIM9_Init 0 */

  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM9_Init 1 */

  /* USER CODE END TIM9_Init 1 */
  htim9.Instance = TIM9;
  htim9.Init.Prescaler = 0;
  htim9.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim9.Init.Period = 65535;
  htim9.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim9.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim9) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim9, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim9, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM9_Init 2 */

  /* USER CODE END TIM9_Init 2 */
  HAL_TIM_MspPostInit(&htim9);

}

/**
  * @brief TIM12 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM12_Init(void)
{

  /* USER CODE BEGIN TIM12_Init 0 */

  /* USER CODE END TIM12_Init 0 */

  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM12_Init 1 */

  /* USER CODE END TIM12_Init 1 */
  htim12.Instance = TIM12;
  // At SYSCLK = HSI 16 MHz (PLL off): Prescaler 15 => 16 MHz / 16 = 1 MHz
  // => 1 tick = 1 us. Period 19999 => 20000 us = 20 ms => 50 Hz servo frame.
  // Pulse compare register is then directly in microseconds (e.g. 1500 = 1.5 ms).
  htim12.Init.Prescaler = 15;
  htim12.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim12.Init.Period = 19999;
  htim12.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim12.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim12) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim12, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM12_Init 2 */

  /* USER CODE END TIM12_Init 2 */
  HAL_TIM_MspPostInit(&htim12);

}

/**
  * @brief USART3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART3_UART_Init(void)
{

  /* USER CODE BEGIN USART3_Init 0 */

  /* USER CODE END USART3_Init 0 */

  /* USER CODE BEGIN USART3_Init 1 */

  /* USER CODE END USART3_Init 1 */
  huart3.Instance = USART3;
  huart3.Init.BaudRate = 115200;
  huart3.Init.WordLength = UART_WORDLENGTH_8B;
  huart3.Init.StopBits = UART_STOPBITS_1;
  huart3.Init.Parity = UART_PARITY_NONE;
  huart3.Init.Mode = UART_MODE_TX_RX;
  huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart3.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART3_Init 2 */

  /* USER CODE END USART3_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(LED3_GPIO_Port, LED3_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(Buzzer_GPIO_Port, Buzzer_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : LED3_Pin */
  GPIO_InitStruct.Pin = LED3_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED3_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : Buzzer_Pin */
  GPIO_InitStruct.Pin = Buzzer_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(Buzzer_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if (huart->Instance == USART3)
  {
    if (rx_byte == '\r' || rx_byte == '\n')
    {
      if (rx_index > 0)
      {
        rx_buf[rx_index] = '\0';

        if (strcmp((char *)rx_buf, "PING") == 0)
        {
          HAL_UART_Transmit(&huart3, pong, sizeof(pong) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "F") == 0)
        {
          pending_move = MOVE_FORWARD;	// actual move runs in the main loop, not here
          HAL_UART_Transmit(&huart3, ack_f, sizeof(ack_f) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "B") == 0)
        {
          pending_move = MOVE_BACKWARD;
          HAL_UART_Transmit(&huart3, ack_b, sizeof(ack_b) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "S") == 0)
        {
          drive_abort = 1;
          pending_move = 0;
          pending_arc = 0;
          pending_arc_deg = 0;
          pending_fw_cm = 0;
          pending_bw_cm = 0;
          pending_fs_cm = 0;
          pending_bs_cm = 0;
          pending_pivot = 0;
          pending_pivot_deg = 0;
          Motors_Stop();
          HAL_UART_Transmit(&huart3, ack_s, sizeof(ack_s) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "SC") == 0)
        {
          Steer_Center();
          HAL_UART_Transmit(&huart3, ack_sc, sizeof(ack_sc) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "SL") == 0)
        {
          Steer_StepLeft();
          HAL_UART_Transmit(&huart3, ack_sl, sizeof(ack_sl) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "SR") == 0)
        {
          Steer_StepRight();
          HAL_UART_Transmit(&huart3, ack_sr, sizeof(ack_sr) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "LL") == 0)
        {
          Steer_LockLeft();
          HAL_UART_Transmit(&huart3, ack_ll, sizeof(ack_ll) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "RR") == 0)
        {
          Steer_LockRight();
          HAL_UART_Transmit(&huart3, ack_rr, sizeof(ack_rr) - 1, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "ENC") == 0)
        {
          char msg[48];
          int n = snprintf(msg, sizeof(msg), "ENC,A,%d,B,%d\r\n",
                           (int)EncoderA_GetCount(), (int)EncoderB_GetCount());
          if (n > 0)
            HAL_UART_Transmit(&huart3, (uint8_t *)msg, (uint16_t)n, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "ENC0") == 0)
        {
          Encoder_Reset();
          HAL_UART_Transmit(&huart3, (uint8_t *)"ACK,ENC0\r\n", 10, HAL_MAX_DELAY);
        }
        else if (strcmp((char *)rx_buf, "IMU") == 0)
        {
          pending_imu = 1;	/* whoami in main loop — never block UART ISR */
        }
        else if (strcmp((char *)rx_buf, "GYRO") == 0)
        {
          pending_gyro = 1;	/* sample in main loop — Init uses HAL_Delay */
        }
        else if (strncmp((char *)rx_buf, "TL ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < ARC_DEG_MIN || deg > ARC_DEG_MAX)
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          else if (MOTION_IDLE())
          {
            pending_arc = ARC_TL;
            pending_arc_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_tl, sizeof(ack_tl) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "TR ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < ARC_DEG_MIN || deg > ARC_DEG_MAX)
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          else if (MOTION_IDLE())
          {
            pending_arc = ARC_TR;
            pending_arc_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_tr, sizeof(ack_tr) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "BL ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < ARC_DEG_MIN || deg > ARC_DEG_MAX)
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          else if (MOTION_IDLE())
          {
            pending_arc = ARC_BL;
            pending_arc_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_bl, sizeof(ack_bl) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "BR ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < ARC_DEG_MIN || deg > ARC_DEG_MAX)
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          else if (MOTION_IDLE())
          {
            pending_arc = ARC_BR;
            pending_arc_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_br, sizeof(ack_br) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "FW ", 3) == 0)
        {
          int cm = atoi((char *)rx_buf + 3);
          if (cm < FW_CM_MIN || cm > FW_CM_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_fw_cm = (uint16_t)cm;
            HAL_UART_Transmit(&huart3, ack_fw, sizeof(ack_fw) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "BW ", 3) == 0)
        {
          int cm = atoi((char *)rx_buf + 3);
          if (cm < FW_CM_MIN || cm > FW_CM_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_bw_cm = (uint16_t)cm;
            HAL_UART_Transmit(&huart3, ack_bw, sizeof(ack_bw) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "FS ", 3) == 0)
        {
          int cm = atoi((char *)rx_buf + 3);
          if (cm < FW_CM_MIN || cm > FW_CM_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_fs_cm = (uint16_t)cm;
            HAL_UART_Transmit(&huart3, ack_fs, sizeof(ack_fs) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "BS ", 3) == 0)
        {
          int cm = atoi((char *)rx_buf + 3);
          if (cm < FW_CM_MIN || cm > FW_CM_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_bs_cm = (uint16_t)cm;
            HAL_UART_Transmit(&huart3, ack_bs, sizeof(ack_bs) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "PL ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < PIVOT_DEG_MIN || deg > PIVOT_DEG_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_pivot = PIVOT_LEFT;
            pending_pivot_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_pl, sizeof(ack_pl) - 1, HAL_MAX_DELAY);
          }
        }
        else if (strncmp((char *)rx_buf, "PR ", 3) == 0)
        {
          int deg = atoi((char *)rx_buf + 3);
          if (deg < PIVOT_DEG_MIN || deg > PIVOT_DEG_MAX)
          {
            HAL_UART_Transmit(&huart3, err_range, sizeof(err_range) - 1, HAL_MAX_DELAY);
          }
          else if (MOTION_IDLE())
          {
            pending_pivot = PIVOT_RIGHT;
            pending_pivot_deg = (uint16_t)deg;
            HAL_UART_Transmit(&huart3, ack_pr, sizeof(ack_pr) - 1, HAL_MAX_DELAY);
          }
        }
        else
        {
          HAL_UART_Transmit(&huart3, err_unknown, sizeof(err_unknown) - 1, HAL_MAX_DELAY);
        }

        rx_index = 0;
        memset(rx_buf, 0, sizeof(rx_buf));
      }

      /* Ignore an empty second terminator - LF in CR+LF */
    }
    else if (rx_byte == '\b' || rx_byte == 0x7F)	// Backspace, or Delete (0x7F -- some terminals send this instead)
    {
      if (rx_index > 0)
      {
        rx_index--;
        uint8_t erase[] = "\b \b";	// move cursor back, blank the char, move back again
        HAL_UART_Transmit(&huart3, erase, sizeof(erase) - 1, HAL_MAX_DELAY);
      }
    }
    else if (rx_index < sizeof(rx_buf) - 1)
    {
      rx_buf[rx_index++] = rx_byte;
    }
    else
    {
      /* Input too long: discard the partial command safely */
      rx_index = 0;
      memset(rx_buf, 0, sizeof(rx_buf));
    }

    HAL_UART_Receive_IT(&huart3, &rx_byte, 1);
  }
}

// --- Motor control (PWM, via TIM4 for Motor A / TIM9 for Motor B) ---
// Each function takes the duty (power level) to drive at.
// Wiring: MotorA_IN1 = TIM4_CH4 (PB9), MotorA_IN2 = TIM4_CH3 (PB8)
//         MotorB_IN1 = TIM9_CH1 (PE5), MotorB_IN2 = TIM9_CH2 (PE6)
// To drive one direction: that side's IN channel gets the duty, the other
// side's IN channel stays at 0. Both at 0 = coast. Both high = brake (AT8236).

void MotorA_Stop(void)
{
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_4, 0);	// IN1
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_3, 0);	// IN2
}

void MotorA_Brake(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_4, duty);
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_3, duty);
}

// NOTE: IN1/IN2 swapped vs. the documented schematic mapping -- on this
// physical robot, Motor A (right wheel) spun backward for "forward" until
// this was flipped empirically. If Motor A is ever rewired/replaced, re-test
// F and flip this back if needed.
void MotorA_Forward(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_4, 0);		// IN1 = 0
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_3, duty);	// IN2 = duty
}

void MotorA_Backward(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_4, duty);	// IN1 = duty
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_3, 0);		// IN2 = 0
}

void MotorB_Stop(void)
{
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, 0);	// IN1
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_2, 0);	// IN2
}

void MotorB_Brake(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, duty);
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_2, duty);
}

void MotorB_Forward(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, duty);	// IN1 = duty
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_2, 0);		// IN2 = 0
}

void MotorB_Backward(uint32_t duty)
{
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_1, 0);		// IN1 = 0
  __HAL_TIM_SET_COMPARE(&htim9, TIM_CHANNEL_2, duty);	// IN2 = duty
}

void Motors_Stop(void)
{
  MotorA_Stop();
  MotorB_Stop();
}

// Short both H-bridge legs so wheels resist freewheel (vs Motors_Stop coast).
void Motors_Brake(void)
{
  MotorA_Brake(FW_BRAKE_DUTY);
  MotorB_Brake(FW_BRAKE_DUTY);
}

void Motors_Forward(void)
{
  MotorA_Forward(MOTOR_DUTY);
  MotorB_Forward(MOTOR_DUTY);
  HAL_Delay(MOVE_DURATION_MS);
  Motors_Stop();
}

void Motors_Backward(void)
{
  MotorA_Backward(MOTOR_DUTY);
  MotorB_Backward(MOTOR_DUTY);
  HAL_Delay(MOVE_DURATION_MS);
  Motors_Stop();
}

// Average |A|,|B| — A counts negative on forward in cal data.
uint32_t Encoder_DistCounts(void)
{
  int32_t a = (int32_t)EncoderA_GetCount();
  int32_t b = (int32_t)EncoderB_GetCount();
  if (a < 0) a = -a;
  if (b < 0) b = -b;
  return (uint32_t)((a + b) / 2);
}

// SC → reset encoders → drive until avg counts hit target → brake → DONE
// dir: 0 = forward (FW/FS), 1 = backward (BW)
static void Drive_CmAt(uint16_t cm, uint32_t duty, uint32_t counts_per_100,
                       uint8_t reverse, uint8_t *done, uint16_t done_len)
{
  uint32_t target = ((uint32_t)cm * counts_per_100) / 100U;
  uint32_t t0;

  drive_abort = 0;

  Steer_Center();
  HAL_Delay(TURN_SERVO_SETTLE_MS);

  Encoder_Reset();
  if (reverse)
  {
    MotorA_Backward(duty);
    MotorB_Backward(duty);
  }
  else
  {
    MotorA_Forward(duty);
    MotorB_Forward(duty);
  }

  t0 = HAL_GetTick();
  while (Encoder_DistCounts() < target)
  {
    if (drive_abort)
      break;
    if ((HAL_GetTick() - t0) > FW_TIMEOUT_MS)
      break;
  }

  Motors_Brake();
  HAL_Delay(FW_BRAKE_MS);
  Motors_Stop();

  if (!drive_abort)
  {
    HAL_UART_Transmit(&huart3, done, done_len, HAL_MAX_DELAY);
  }
}

void Drive_ForwardCm(uint16_t cm)
{
  Drive_CmAt(cm, MOTOR_DUTY, COUNTS_PER_100CM, 0, done_fw, (uint16_t)(sizeof(done_fw) - 1));
}

void Drive_BackwardCm(uint16_t cm)
{
  Drive_CmAt(cm, MOTOR_DUTY, COUNTS_PER_100CM, 1, done_bw, (uint16_t)(sizeof(done_bw) - 1));
}

void Drive_ForwardSlowCm(uint16_t cm)
{
  Drive_CmAt(cm, FS_DUTY, COUNTS_PER_100CM_FS, 0, done_fs, (uint16_t)(sizeof(done_fs) - 1));
}

void Drive_BackwardSlowCm(uint16_t cm)
{
  /* Same slow duty + FS cal until a separate BS tape cal exists. */
  Drive_CmAt(cm, FS_DUTY, COUNTS_PER_100CM_FS, 1, done_bs, (uint16_t)(sizeof(done_bs) - 1));
}

// On-spot pivot: integrate ICM20948 yaw (Z) until |angle| hits command → brake → ACK.
// Z+ = left, Z− = right (Carl hand-cal 2026-09-11). Timed timeout is failsafe only.
void Pivot_Run(uint8_t pivot_dir, uint16_t deg)
{
  float bias_z = 0.0f;
  float angle_deg = 0.0f;
  float target = (float)deg - PIVOT_STOP_MARGIN_DEG;
  uint32_t t0, t_prev, timeout_ms;
  int i;

  drive_abort = 0;

  if (target < 1.0f)
    target = 1.0f;

  (void)ICM20948_Init();

  /* Bias while still — car should not be moving. */
  for (i = 0; i < PIVOT_BIAS_SAMPLES; i++)
  {
    int16_t gx = 0, gy = 0, gz = 0;
    if (ICM20948_ReadGyroDps(&gx, &gy, &gz) == 0)
      bias_z += (float)gz;
    HAL_Delay(PIVOT_BIAS_DT_MS);
  }
  bias_z /= (float)PIVOT_BIAS_SAMPLES;

  if (pivot_dir == PIVOT_LEFT)
  {
    MotorA_Forward(PIVOT_DUTY_FWD);	/* A forward strong */
    MotorB_Backward(PIVOT_DUTY_REV);	/* B reverse weak */
  }
  else
  {
    MotorA_Backward(PIVOT_DUTY_REV);	/* A reverse weak */
    MotorB_Forward(PIVOT_DUTY_FWD);	/* B forward strong */
  }

  timeout_ms = ((uint32_t)deg * (uint32_t)PIVOT_TIMEOUT_MS_PER_90) / 90U;
  t0 = HAL_GetTick();
  t_prev = t0;

  while ((HAL_GetTick() - t0) < timeout_ms)
  {
    int16_t gx = 0, gy = 0, gz = 0;
    uint32_t t_now;
    float dt_s;
    float rate;

    if (drive_abort)
      break;

    if (ICM20948_ReadGyroDps(&gx, &gy, &gz) != 0)
      continue;

    t_now = HAL_GetTick();
    dt_s = (float)(t_now - t_prev) * 0.001f;
    t_prev = t_now;
    if (dt_s <= 0.0f || dt_s > 0.05f)
      dt_s = 0.01f;

    rate = (float)gz - bias_z;
    angle_deg += rate * dt_s;

    if (pivot_dir == PIVOT_LEFT)
    {
      if (angle_deg >= target)
        break;
    }
    else
    {
      if (angle_deg <= -target)
        break;
    }
  }

  Motors_Brake();
  HAL_Delay(FW_BRAKE_MS);
  Motors_Stop();

  if (!drive_abort)
  {
    if (pivot_dir == PIVOT_LEFT)
      HAL_UART_Transmit(&huart3, done_pl, sizeof(done_pl) - 1, HAL_MAX_DELAY);
    else
      HAL_UART_Transmit(&huart3, done_pr, sizeof(done_pr) - 1, HAL_MAX_DELAY);
  }
}

// Gyro Ackermann arc: LL/RR → drive 20% fwd/rev → integrate |yaw Z| → brake → SC → DONE.
// BL/BR = reverse + same locks (not old skid spins). Stop uses |Δθ| so reverse sign is OK.
void Arc_Run(uint8_t arc_kind, uint16_t deg)
{
  float bias_z = 0.0f;
  float angle_deg = 0.0f;
  float target = (float)deg * (1.0f - ARC_STOP_EARLY_PCT / 100.0f);
  uint32_t t0, t_prev, timeout_ms;
  uint8_t *done;
  uint16_t done_len;
  int i;
  int reverse;

  drive_abort = 0;

  if (target < 1.0f)
    target = 1.0f;

  reverse = (arc_kind == ARC_BL || arc_kind == ARC_BR) ? 1 : 0;

  if (arc_kind == ARC_TL)
  {
    done = done_tl;
    done_len = (uint16_t)(sizeof(done_tl) - 1);
  }
  else if (arc_kind == ARC_TR)
  {
    done = done_tr;
    done_len = (uint16_t)(sizeof(done_tr) - 1);
  }
  else if (arc_kind == ARC_BL)
  {
    done = done_bl;
    done_len = (uint16_t)(sizeof(done_bl) - 1);
  }
  else
  {
    done = done_br;
    done_len = (uint16_t)(sizeof(done_br) - 1);
  }

  (void)ICM20948_Init();

  for (i = 0; i < ARC_BIAS_SAMPLES; i++)
  {
    int16_t gx = 0, gy = 0, gz = 0;
    if (ICM20948_ReadGyroDps(&gx, &gy, &gz) == 0)
      bias_z += (float)gz;
    HAL_Delay(ARC_BIAS_DT_MS);
  }
  bias_z /= (float)ARC_BIAS_SAMPLES;

  if (arc_kind == ARC_TL || arc_kind == ARC_BL)
    Steer_LockLeft();
  else
    Steer_LockRight();
  HAL_Delay(TURN_SERVO_SETTLE_MS);

  if (!reverse)
  {
    MotorA_Forward(TURN_ARC_DUTY);
    MotorB_Forward(TURN_ARC_DUTY);
  }
  else
  {
    MotorA_Backward(TURN_ARC_DUTY);
    MotorB_Backward(TURN_ARC_DUTY);
  }

  timeout_ms = ((uint32_t)deg * (uint32_t)ARC_TIMEOUT_MS_PER_90) / 90U;
  t0 = HAL_GetTick();
  t_prev = t0;

  while ((HAL_GetTick() - t0) < timeout_ms)
  {
    int16_t gx = 0, gy = 0, gz = 0;
    uint32_t t_now;
    float dt_s;
    float rate;

    if (drive_abort)
      break;

    if (ICM20948_ReadGyroDps(&gx, &gy, &gz) != 0)
      continue;

    t_now = HAL_GetTick();
    dt_s = (float)(t_now - t_prev) * 0.001f;
    t_prev = t_now;
    if (dt_s <= 0.0f || dt_s > 0.05f)
      dt_s = 0.01f;

    rate = (float)gz - bias_z;
    angle_deg += rate * dt_s;

    if (fabsf(angle_deg) >= target)
      break;
  }

  Motors_Brake();
  HAL_Delay(FW_BRAKE_MS);
  Motors_Stop();

  Steer_Center();
  HAL_Delay(TURN_SERVO_SETTLE_MS);

  if (!drive_abort)
    HAL_UART_Transmit(&huart3, done, done_len, HAL_MAX_DELAY);
}

// --- Front-wheel steering (servo) ---
// SC = center; SL/SR = nudge (±SERVO_STEP_US); LL/RR = jump to soft min/max.
// Creep with SL/SR to find mechanical ends, then tighten SERVO_MIN/MAX.
// Direction of SL/LL vs SR/RR not verified on hardware yet.

void Steer_SetPulse(uint32_t us)
{
  if (us < SERVO_MIN_US) us = SERVO_MIN_US;
  if (us > SERVO_MAX_US) us = SERVO_MAX_US;
  servo_pulse_us = us;
  __HAL_TIM_SET_COMPARE(&htim12, TIM_CHANNEL_2, servo_pulse_us);
}

void Steer_Center(void)
{
  Steer_SetPulse(SERVO_CENTER_US);
}

void Steer_StepLeft(void)
{
  Steer_SetPulse(servo_pulse_us - SERVO_STEP_US);
}

void Steer_StepRight(void)
{
  Steer_SetPulse(servo_pulse_us + SERVO_STEP_US);
}

void Steer_LockLeft(void)
{
  Steer_SetPulse(SERVO_MIN_US);
}

void Steer_LockRight(void)
{
  Steer_SetPulse(SERVO_MAX_US);
}

static void MX_I2C2_Init(void)
{
  hi2c2.Instance = I2C2;
  hi2c2.Init.ClockSpeed = 100000;
  hi2c2.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c2.Init.OwnAddress1 = 0;
  hi2c2.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c2.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c2.Init.OwnAddress2 = 0;
  hi2c2.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c2.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* Select user bank 0 and read WHO_AM_I. Returns 0 on I2C OK (id may still be wrong). */
int ICM20948_WhoAmI(uint8_t *id_out)
{
  uint8_t bank = 0x00;
  uint8_t id = 0;

  if (id_out)
    *id_out = 0;

  if (HAL_I2C_Mem_Write(&hi2c2, ICM20948_ADDR_8BIT, ICM20948_REG_BANK_SEL,
                        I2C_MEMADD_SIZE_8BIT, &bank, 1, 100) != HAL_OK)
    return -1;

  if (HAL_I2C_Mem_Read(&hi2c2, ICM20948_ADDR_8BIT, ICM20948_REG_WHO_AM_I,
                       I2C_MEMADD_SIZE_8BIT, &id, 1, 100) != HAL_OK)
    return -1;

  if (id_out)
    *id_out = id;
  return 0;
}

static int ICM20948_SelectBank(uint8_t bank)
{
  uint8_t v = (uint8_t)(bank << 4);
  if (HAL_I2C_Mem_Write(&hi2c2, ICM20948_ADDR_8BIT, ICM20948_REG_BANK_SEL,
                        I2C_MEMADD_SIZE_8BIT, &v, 1, 100) != HAL_OK)
    return -1;
  return 0;
}

static int ICM20948_WriteReg(uint8_t reg, uint8_t val)
{
  if (HAL_I2C_Mem_Write(&hi2c2, ICM20948_ADDR_8BIT, reg,
                        I2C_MEMADD_SIZE_8BIT, &val, 1, 100) != HAL_OK)
    return -1;
  return 0;
}

/* Wake chip, enable gyro at ±2000 dps. Full reset only once. */
int ICM20948_Init(void)
{
  static uint8_t icm_ready = 0;
  uint8_t id = 0;

  if (icm_ready)
    return 0;

  if (ICM20948_WhoAmI(&id) != 0 || id != ICM20948_WHO_AM_I_VAL)
    return -1;

  if (ICM20948_SelectBank(0) != 0)
    return -1;
  if (ICM20948_WriteReg(ICM20948_REG_PWR_MGMT_1, 0x80) != 0)	/* device reset */
    return -1;
  HAL_Delay(100);

  if (ICM20948_SelectBank(0) != 0)
    return -1;
  if (ICM20948_WriteReg(ICM20948_REG_PWR_MGMT_1, 0x01) != 0)	/* auto clk, wake */
    return -1;
  HAL_Delay(10);
  if (ICM20948_WriteReg(ICM20948_REG_LP_CONFIG, 0x00) != 0)	/* not duty-cycled */
    return -1;
  if (ICM20948_WriteReg(ICM20948_REG_PWR_MGMT_2, 0x00) != 0)	/* enable accel+gyro */
    return -1;
  HAL_Delay(30);

  /* Bank 2: sample rate div + GYRO_CONFIG_1 (±2000 dps, DLPF on) */
  if (ICM20948_SelectBank(2) != 0)
    return -1;
  if (ICM20948_WriteReg(ICM20948_REG_GYRO_SMPLRT_DIV, 0x00) != 0)
    return -1;
  if (ICM20948_WriteReg(ICM20948_REG_GYRO_CONFIG_1, 0x07) != 0)
    return -1;

  if (ICM20948_SelectBank(0) != 0)
    return -1;

  icm_ready = 1;
  return 0;
}

void Imu_Report(void)
{
  uint8_t id = 0;
  char msg[40];
  int n;

  if (ICM20948_WhoAmI(&id) == 0 && id == ICM20948_WHO_AM_I_VAL)
    n = snprintf(msg, sizeof(msg), "IMU,OK,%02X\r\n", id);
  else
    n = snprintf(msg, sizeof(msg), "IMU,ERR,%02X\r\n", id);
  if (n > 0)
    HAL_UART_Transmit(&huart3, (uint8_t *)msg, (uint16_t)n, HAL_MAX_DELAY);
}

void Gyro_Report(void)
{
  /* Gyro = rate while turning, NOT heading after you stop. Spam GYRO while rotating. */
  int16_t gx = 0, gy = 0, gz = 0;
  int16_t rx = 0, ry = 0, rz = 0;
  int16_t ax = 0, ay = 0, az = 0;
  char msg[96];
  int n;

  (void)ICM20948_Init();
  if (ICM20948_ReadGyroRaw(&rx, &ry, &rz) == 0 &&
      ICM20948_ReadAccelRaw(&ax, &ay, &az) == 0)
  {
    gx = (int16_t)(((int32_t)rx * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
    gy = (int16_t)(((int32_t)ry * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
    gz = (int16_t)(((int32_t)rz * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
    n = snprintf(msg, sizeof(msg),
                 "GYRO,X,%d,Y,%d,Z,%d,RX,%d,RY,%d,RZ,%d,AX,%d,AY,%d,AZ,%d\r\n",
                 (int)gx, (int)gy, (int)gz,
                 (int)rx, (int)ry, (int)rz,
                 (int)ax, (int)ay, (int)az);
  }
  else
    n = snprintf(msg, sizeof(msg), "GYRO,ERR\r\n");
  if (n > 0)
    HAL_UART_Transmit(&huart3, (uint8_t *)msg, (uint16_t)n, HAL_MAX_DELAY);
}

int ICM20948_ReadGyroRaw(int16_t *gx, int16_t *gy, int16_t *gz)
{
  uint8_t raw[6];

  if (ICM20948_SelectBank(0) != 0)
    return -1;

  if (HAL_I2C_Mem_Read(&hi2c2, ICM20948_ADDR_8BIT, ICM20948_REG_GYRO_XOUT_H,
                       I2C_MEMADD_SIZE_8BIT, raw, 6, 100) != HAL_OK)
    return -1;

  if (gx)
    *gx = (int16_t)((raw[0] << 8) | raw[1]);
  if (gy)
    *gy = (int16_t)((raw[2] << 8) | raw[3]);
  if (gz)
    *gz = (int16_t)((raw[4] << 8) | raw[5]);
  return 0;
}

int ICM20948_ReadAccelRaw(int16_t *ax, int16_t *ay, int16_t *az)
{
  uint8_t raw[6];

  if (ICM20948_SelectBank(0) != 0)
    return -1;

  if (HAL_I2C_Mem_Read(&hi2c2, ICM20948_ADDR_8BIT, ICM20948_REG_ACCEL_XOUT_H,
                       I2C_MEMADD_SIZE_8BIT, raw, 6, 100) != HAL_OK)
    return -1;

  if (ax)
    *ax = (int16_t)((raw[0] << 8) | raw[1]);
  if (ay)
    *ay = (int16_t)((raw[2] << 8) | raw[3]);
  if (az)
    *az = (int16_t)((raw[4] << 8) | raw[5]);
  return 0;
}

/* Gyro rates in whole °/s (integer). Returns 0 on success. */
int ICM20948_ReadGyroDps(int16_t *gx_dps, int16_t *gy_dps, int16_t *gz_dps)
{
  int16_t rx, ry, rz;

  if (ICM20948_ReadGyroRaw(&rx, &ry, &rz) != 0)
    return -1;

  /* dps = raw * 100 / 1640  (±2000 scale) */
  if (gx_dps)
    *gx_dps = (int16_t)(((int32_t)rx * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
  if (gy_dps)
    *gy_dps = (int16_t)(((int32_t)ry * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
  if (gz_dps)
    *gz_dps = (int16_t)(((int32_t)rz * 100) / ICM20948_GYRO_DPS_PER_LSB_X100);
  return 0;
}

static void MX_TIM2_Init(void)
{  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* Motor A encoder: TIM2_CH1=PA15, TIM2_CH2=PB3 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 65535;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 4;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 4;
  if (HAL_TIM_Encoder_Init(&htim2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
}

static void MX_TIM3_Init(void)
{
  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* Motor B encoder: TIM3_CH1=PB4, TIM3_CH2=PB5 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 65535;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 4;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 4;
  if (HAL_TIM_Encoder_Init(&htim3, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
}

int16_t EncoderA_GetCount(void)
{
  return (int16_t)__HAL_TIM_GET_COUNTER(&htim2);
}

int16_t EncoderB_GetCount(void)
{
  return (int16_t)__HAL_TIM_GET_COUNTER(&htim3);
}

void Encoder_Reset(void)
{
  __HAL_TIM_SET_COUNTER(&htim2, 0);
  __HAL_TIM_SET_COUNTER(&htim3, 0);
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
