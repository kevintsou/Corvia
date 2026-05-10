int unused_local(void) {
    int used = 5;
    int unused = 10;
    return used;
}

void unused_param(int x, int y) {
    int result = x * 2;
    (void)result;
}

struct Point { int x; int y; };

struct Point unused_tag_decl(void) {
    struct Point p;
    p.x = 1;
    p.y = 2;
    return p;
}

int safe_all_used(int a, int b) {
    int sum = a + b;
    return sum;
}
