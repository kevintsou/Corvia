void oob_read(void) {
    int arr[5];
    int x = arr[5];
    int y = arr[10];
    (void)x;
    (void)y;
}

void oob_write(void) {
    int buf[4];
    buf[4] = 99;
    buf[-1] = 0;
}

void safe_access(void) {
    int arr[5];
    int i;
    for (i = 0; i < 5; i++) {
        arr[i] = i;
    }
    int x = arr[4];
    (void)x;
}
