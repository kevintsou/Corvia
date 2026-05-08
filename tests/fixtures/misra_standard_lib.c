void *malloc(unsigned long n);
void free(void *p);
int printf(const char *fmt, ...);
int atoi(const char *s);
void abort(void);
void exit(int code);
int system(const char *cmd);
int setjmp(int *env);
void longjmp(int *env, int v);

int __reserved_var;

void usage(void) {
    char *p = (char *)malloc(16);
    free(p);
    printf("hi\n");
    int n = atoi("3");
    if (n == 0) {
        abort();
    }
    system("ls");
    int env;
    setjmp(&env);
    longjmp(&env, 1);
    exit(0);
}
