int use_before_init(void) {
    int x;
    return x;
}

int partial_init(int cond) {
    int val;
    if (cond) {
        val = 10;
    }
    return val;
}

int safe_init(void) {
    int x = 0;
    return x;
}
