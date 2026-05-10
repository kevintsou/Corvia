void pointer_arithmetic(int *p, int n) {
    int *q = p + n;
    int *r = p - 1;
    q++;
    (void)q;
    (void)r;
}

int *return_local_addr(void) {
    int local = 42;
    return &local;
}

void pointer_comparison(int *p, int *q) {
    int arr[5];
    int *a = &arr[0];
    int *b = &arr[4];
    int diff = b - a;
    (void)diff;
    (void)p;
    (void)q;
}

int safe_pointer(int *arr, int idx, int len) {
    if (idx >= 0 && idx < len) {
        return arr[idx];
    }
    return 0;
}
