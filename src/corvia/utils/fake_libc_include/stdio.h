#ifndef _STDIO_H
#define _STDIO_H

/* Minimal fake stdio.h for pycparser (used with -nostdinc). */

typedef unsigned int size_t;

#ifndef NULL
#define NULL ((void *)0)
#endif

typedef struct _FILE FILE;

int   printf(const char *format, ...);
int   sprintf(char *str, const char *format, ...);
int   snprintf(char *str, size_t size, const char *format, ...);
int   puts(const char *s);
int   putchar(int c);

#endif /* _STDIO_H */
