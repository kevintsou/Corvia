#ifndef ARM_COMPAT_H
#define ARM_COMPAT_H

typedef unsigned int uint32_t;
typedef unsigned short uint16_t;
typedef unsigned char uint8_t;
typedef unsigned long ulong;
typedef unsigned int size_t;

#define ALIGNED(x) __attribute__((aligned(x)))
#define PACKED __attribute__((packed))
#define WEAK __attribute__((weak))

#endif