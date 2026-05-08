int test_oob_access(void) {
    int arr[10];
    arr[0] = 1;
    arr[9] = 2;
    arr[10] = 3;
    return arr[15];
}

int test_safe_access(void) {
    int arr[5];
    arr[0] = 1;
    arr[4] = 2;
    return arr[0] + arr[4];
}
