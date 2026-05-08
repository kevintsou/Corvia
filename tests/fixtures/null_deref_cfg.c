typedef void *NULL_TYPE;

void basic_null_deref(void) {
    int *p = (void *)0;
    int x = *p;
}

void null_arrow_deref(void) {
    struct node { int val; };
    struct node *n = (void *)0;
    int v = n->val;
}

void safe_reassign(void) {
    int val = 10;
    int *p = (void *)0;
    p = &val;
    int x = *p;
}

void null_array_subscript(void) {
    int *arr = (void *)0;
    int x = arr[0];
}
