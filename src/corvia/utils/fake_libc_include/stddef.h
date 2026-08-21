#ifndef _STDDEF_H
#define _STDDEF_H

/* Minimal fake stddef.h for pycparser (used with -nostdinc). */

typedef unsigned int size_t;
typedef int          ptrdiff_t;
typedef unsigned int wchar_t;

#ifndef NULL
#define NULL ((void *)0)
#endif

#ifndef offsetof
#define offsetof(type, member) ((size_t) &((type *)0)->member)
#endif

#endif /* _STDDEF_H */
