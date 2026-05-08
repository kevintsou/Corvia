int test_dead_after_return(int x) {
    return x;
    x = x + 1;
}

int test_always_true(void) {
    if (1) {
        return 1;
    }
    return 0;
}

int test_always_false(void) {
    if (0) {
        return 1;
    }
    return 0;
}

int test_no_dead_code(int x) {
    if (x > 0) {
        return 1;
    }
    return 0;
}
