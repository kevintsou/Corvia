typedef struct A { int x; } A;
typedef struct B { int y; } B;

void use(int *p);
void use_a(A *p);

int func_ptr_cast(void) {
    void (*fp)(int *) = use;
    int *ip = (int *)fp;
    return (int)ip;
}

void object_pointer_cross(void) {
    A a;
    A *pa = &a;
    B *pb = (B *)pa;
    use_a(pa);
    (void)pb;
}

void void_to_object(void) {
    void *vp = 0;
    int *ip = (int *)vp;
    (void)ip;
}

void float_pointer(void) {
    int *ip = 0;
    float f = (float)(unsigned long)ip;
    A *pa = 0;
    float g = (float)(unsigned long)pa;
    (void)f; (void)g;
}

void object_to_float(int *ip) {
    float as_float = (float)ip;
    (void)as_float;
}

void const_drop(const int *cp) {
    int *p = (int *)cp;
    (void)p;
}

void use_zero_constant(void) {
    int *p = 0;
    (void)p;
}

/* Pointer hidden behind a typedef: (HCMD_PTR)void_ptr must be read as a
   void->object pointer conversion (11.5), NOT a pointer/integer (11.4) or
   void/arithmetic (11.6) conversion. Regression guard for typedef pointer
   resolution. */
typedef struct hcmd { int ctag; } HCMD;
typedef HCMD *HCMD_PTR;

int typedef_pointer_cast(void *dptr) {
    HCMD_PTR hp = (HCMD_PTR)dptr;
    return hp->ctag;
}
