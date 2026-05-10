void missing_braces(int x) {
    if (x > 0)
        x = x + 1;

    int i;
    for (i = 0; i < 10; i++)
        x = x + i;

    while (x > 0)
        x = x - 1;
}

int assign_in_if(int x) {
    int y = 0;
    if (y = x + 1) {
        return y;
    }
    return 0;
}

void safe_braces(int x) {
    if (x > 0) {
        x = x + 1;
    }
    int i;
    for (i = 0; i < 10; i++) {
        x = x + i;
    }
}
