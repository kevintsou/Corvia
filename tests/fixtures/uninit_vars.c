int test_basic_uninit(void) {
    int x;
    return x;
}

struct point {
    int x;
    int y;
    int z;
};

int test_partial_struct(void) {
    struct point p;
    p.x = 1;
    p.y = 2;
    return p.x + p.y + p.z;
}

int test_initialized(void) {
    int a = 10;
    int b = 20;
    return a + b;
}
