int dead_after_return(int x) {
    if (x > 0) {
        return x;
        int unreachable = 5;
        (void)unreachable;
    }
    return 0;
}

void dead_after_break(int x) {
    int i;
    for (i = 0; i < 10; i++) {
        if (i == 3) {
            break;
            x = 99;
        }
    }
    (void)x;
}

int invariant_condition(void) {
    int x = 5;
    if (x > 10) {
        return 1;
    }
    return 0;
}

int safe_reachable(int x) {
    if (x > 0) {
        return x * 2;
    }
    return -x;
}
