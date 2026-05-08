int test_goto(int x) {
    if (x > 0) {
        goto end;
    }
    x = 0;
end:
    return x;
}

int test_elseif_no_else(int x) {
    if (x > 10) {
        return 2;
    } else if (x > 0) {
        return 1;
    }
    return 0;
}

int test_multi_return(int x) {
    if (x > 0) {
        return 1;
    }
    if (x < 0) {
        return -1;
    }
    return 0;
}
