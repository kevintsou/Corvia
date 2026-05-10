typedef unsigned long size_t;
void *malloc(size_t size);
void free(void *ptr);

void leaky_function(void) {
    int *buf = (int *)malloc(100 * sizeof(int));
    buf[0] = 1;
}

int safe_function(void) {
    int *p = (int *)malloc(sizeof(int));
    if (p == 0) {
        return 1;
    }
    *p = 10;
    free(p);
    return 0;
}
