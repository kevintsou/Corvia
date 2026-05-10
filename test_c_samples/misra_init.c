struct Point { int x; int y; };

void bad_init(void) {
    int arr[4] = {1, 2, 3};

    struct Point p = {1};

    int matrix[2][2] = {1, 2, 3, 4};
    (void)arr;
    (void)p;
    (void)matrix;
}

void good_init(void) {
    int arr[4] = {1, 2, 3, 4};

    struct Point p = {1, 2};

    int matrix[2][2] = {{1, 2}, {3, 4}};
    (void)arr;
    (void)p;
    (void)matrix;
}
