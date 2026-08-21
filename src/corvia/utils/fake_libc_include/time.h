#ifndef _TIME_H
#define _TIME_H

/* Minimal fake time.h for pycparser (used with -nostdinc).
   Pulled in transitively by e.g. mbedtls/platform_time.h. Only the type/name
   surface is needed for static analysis; Corvia's _COMMON_TYPE_STUBS also
   injects time_t/clock_t. */

typedef unsigned long time_t;
typedef unsigned long clock_t;
typedef unsigned int  size_t;

struct tm {
    int tm_sec;
    int tm_min;
    int tm_hour;
    int tm_mday;
    int tm_mon;
    int tm_year;
    int tm_wday;
    int tm_yday;
    int tm_isdst;
};

time_t     time(time_t *t);
clock_t    clock(void);
double     difftime(time_t end, time_t beginning);
time_t     mktime(struct tm *timeptr);
struct tm *localtime(const time_t *timer);
struct tm *gmtime(const time_t *timer);

#endif /* _TIME_H */
