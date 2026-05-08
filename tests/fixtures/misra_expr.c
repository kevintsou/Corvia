int test_shift(int x) {
    int a = x << 33;
    return a;
}

int test_comma(void) {
    int a;
    int b;
    a = (b = 1, b + 2);
    return a;
}

int test_sizeof_side_effect(void) {
    int x = 5;
    int s = sizeof(x++);
    return s;
}
