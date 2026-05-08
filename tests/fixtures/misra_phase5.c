typedef struct _IO_FILE FILE;
FILE *fopen(const char *p, const char *m);
int fclose(FILE *f);

struct never_used { int x; int y; };

typedef int atomic_int;
typedef int thrd_t;
int thrd_create(thrd_t *t, int (*f)(void *), void *arg);
int atomic_load(atomic_int *o);

void emergent_use(void) {
    atomic_int counter;
    thrd_t worker;
    thrd_create(&worker, 0, 0);
    atomic_load(&counter);
}

void file_deref(const char *path) {
    FILE *f = fopen(path, "r");
    int x = *f;
    (void)x;
    fclose(f);
}

int nested_label(int x) {
    int y = 0;
    switch (x) {
        case 1:
            {
                case 2:
                    y = 2;
                    break;
            }
        default:
            y = 0;
            break;
    }
    return y;
}

int unused_label(int x) {
    int y = 0;
    if (x) {
        goto done;
    }
    y = 1;
done:
    return y;
unused_one:
    return -1;
}

struct point { int x; int y; };
int scalar_to_struct = 0;
struct point unbraced_struct = 0;
struct point braced_struct = {1, 2};

int partial[5] = {1, 2};
int full[3] = {1, 2, 3};
