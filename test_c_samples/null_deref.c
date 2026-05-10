typedef unsigned long size_t;
void *malloc(size_t size);
void free(void *ptr);

int deref_without_check(void) {
    int *p = (int *)malloc(sizeof(int));
    return *p;
}

int explicit_null(void) {
    int *q = 0;
    return *q;
}

int safe_version(int *p) {
    if (p != 0) {
        return *p;
    }
    return 0;
}
