/**
 * @file funconfig.h
 * @brief ch32v003fun compile-time configuration for the wire-encoder driver build.
 *
 * Sets the framework's FUNCONF_* options for this build. Debug printf over SWIO
 * is off (it distorts HIL timing); tracing goes out the PD6 debug UART instead
 * (`common/debug_uart`, driver phase only). The driver paces with raw
 * SysTick->CNT arithmetic, so SysTick runs on full HCLK.
 */
#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_DEBUGPRINTF 0  /**< Non-default: no debugprintf over SWIO — it distorts HIL timing. */
#define FUNCONF_USE_UARTPRINTF  0  /**< No framework UART printf — common/debug_uart owns PD6. */
#define FUNCONF_SYSTICK_USE_HCLK 1 /**< Non-default: SysTick on full HCLK (48 MHz), not the default HCLK/8. */

#endif
