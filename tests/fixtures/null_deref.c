int test_null_deref(void) {
    int *p = 0;
    return *p;
}

struct node {
    int value;
    struct node *next;
};

int test_null_arrow(void) {
    struct node *n = 0;
    return n->value;
}

int test_safe_check(int *p) {
    if (p != 0) {
        return *p;
    }
    return 0;
}
