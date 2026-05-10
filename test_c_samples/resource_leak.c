typedef void *FILE;
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *fp);
int fgets(char *s, int n, FILE *fp);

void process_file_leak(const char *path) {
    FILE *f = fopen(path, "r");
    if (f == 0) {
        return;
    }
    char buf[256];
    fgets(buf, 256, f);
}

void process_file_safe(const char *path) {
    FILE *f = fopen(path, "r");
    if (f == 0) {
        return;
    }
    char buf[256];
    fgets(buf, 256, f);
    fclose(f);
}
