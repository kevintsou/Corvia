typedef int MyType;
typedef int MyType;

int outer_var = 0;

int shadow_test(void) {
    int outer_var = 5;
    return outer_var;
}

struct MyStruct { int x; };
struct MyStruct { int y; };

typedef int uint32;

int safe_unique(void) {
    int local_a = 1;
    int local_b = 2;
    return local_a + local_b;
}
