typedef unsigned long size_t;
void *malloc(size_t size);
void free(void *ptr);

static int add(int a, int b) {
    return a + b;
}

static int compute(int x, int y) {
    return add(x, y) * 2;
}

int safe_arithmetic(void) {
    int a = 10;
    int b = 20;
    int result = compute(a, b);
    return result;
}

int safe_pointer(int *p) {
    if (p == 0) {
        return -1;
    }
    return *p + 1;
}
