union Data {
    int i;
    float f;
    char c;
};

union Data make_data(int val) {
    union Data d;
    d.i = val;
    return d;
}

int read_union(union Data d) {
    return d.i;
}
