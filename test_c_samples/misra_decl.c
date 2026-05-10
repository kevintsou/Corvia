int implicit_type_func();

void no_prototype();

extern int shared_var;
extern int shared_var;

static int file_local = 0;

int could_be_static(void) {
    return file_local + 1;
}

int safe_decl(void);
int safe_decl(void) {
    return 42;
}
