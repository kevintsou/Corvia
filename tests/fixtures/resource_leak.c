typedef void *FILE;
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *fp);
int fprintf(FILE *fp, const char *fmt);

void leak_file(void) {
    FILE *fp = fopen("test.txt", "r");
    fprintf(fp, "hello");
}

void no_leak_file(void) {
    FILE *fp = fopen("test.txt", "r");
    fprintf(fp, "hello");
    fclose(fp);
}

void use_after_close(void) {
    FILE *fp = fopen("test.txt", "w");
    fclose(fp);
    fprintf(fp, "bad");
}

void conditional_file_leak(int flag) {
    FILE *fp = fopen("data.csv", "r");
    if (flag) {
        fclose(fp);
    }
}
