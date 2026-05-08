typedef unsigned long size_t;
typedef void *FILE;
void *malloc(size_t size);
void *calloc(size_t num, size_t size);
void free(void *ptr);

void leak_basic(void) {
    int *p = (int *)malloc(sizeof(int) * 10);
    p[0] = 42;
}

void no_leak(void) {
    int *p = (int *)malloc(sizeof(int) * 10);
    p[0] = 42;
    free(p);
}

void conditional_leak(int flag) {
    int *p = (int *)malloc(sizeof(int));
    if (flag) {
        free(p);
    }
}

void double_alloc_leak(void) {
    int *a = (int *)malloc(10);
    int *b = (int *)malloc(20);
    free(a);
}
