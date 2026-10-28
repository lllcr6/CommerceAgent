"""Export and audit the frozen English dataset without making model requests.

First generate/resume source expressions with make roberta-corpus.
make roberta-dataset performs leakage checks and exports the three partitions.
"""
from scripts.roberta.english_dataset import export


def main():
    export()


if __name__ == '__main__':
    main()
