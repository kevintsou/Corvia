typedef unsigned long size_t;
void *malloc(size_t size);
int printf(const char *fmt, ...);

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

void check_switch(int x) {
    switch (x) {
        case 1:
            printf("one\n");
            break;
        case 2:
            printf("two\n");
        case 3:
            printf("three\n");
            break;
    }
}

void bad_literals(void) {
    int octal = 0755;
    long val = 100l;
    char *s = "hello";
    (void)octal;
    (void)val;
    (void)s;
}

void ignore_return(void) {
    malloc(10);
}
