union variant {
    int i;
    float f;
    char *s;
};

void use_union(void) {
    union variant v;
    v.i = 1;
    (void)v;
}
