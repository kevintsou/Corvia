int test_syntax(int x) {
    if (x = 5) {
        return 1;
    }

    if (x > 0)
        return 1;

    while (x > 0)
        x = x - 1;

    return 0;
}
