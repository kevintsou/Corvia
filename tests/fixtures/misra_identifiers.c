int outer_var;

int func(int outer_var) {
    int inner_local;
    {
        int inner_local;
        int outer_var;
    }
    return outer_var;
}

struct mything { int x; };
union mything { int u; };
