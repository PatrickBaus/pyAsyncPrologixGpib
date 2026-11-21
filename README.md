# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/PatrickBaus/pyAsyncPrologixGpib/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                              |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| prologix\_gpib\_async/\_\_init\_\_.py             |        5 |        0 |        0 |        0 |    100% |           |
| prologix\_gpib\_async/ip\_connection.py           |      220 |       50 |       48 |       14 |     73% |78-84, 101-\>exit, 123, 133, 143, 173-174, 179, 183, 195, 202-212, 238, 248, 252, 266-277, 298-310, 319-\>exit, 337-341, 417-421, 434-\>exit, 441-\>446, 463, 475, 486, 515, 530-\>533, 550, 576 |
| prologix\_gpib\_async/prologix\_gpib\_async.py    |      322 |       76 |       52 |        7 |     77% |95, 115, 165, 189-191, 197, 319-\>325, 329, 341-342, 354-355, 373-374, 388-389, 400, 415-429, 441-442, 460-461, 474-475, 494-495, 508-509, 528-529, 542-543, 560-561, 572-577, 586, 597-598, 615, 621-623, 632-634, 646-650, 656-658, 664-666, 687, 710-712, 739-741, 762-\>766, 837-838, 858-859, 871, 880-881 |
| prologix\_gpib\_async/prologix\_gpib\_base.py     |       68 |       18 |        0 |        0 |     74% |60, 67, 74, 81, 88, 134, 141, 148, 155, 162, 169, 176, 183, 190, 197, 204, 211, 218 |
| prologix\_gpib\_async/prologix\_gpib\_ethernet.py |       23 |        4 |        0 |        0 |     83% |25, 35, 75, 85 |
| **TOTAL**                                         |  **638** |  **148** |  **100** |   **21** | **76%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/PatrickBaus/pyAsyncPrologixGpib/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/pyAsyncPrologixGpib/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/PatrickBaus/pyAsyncPrologixGpib/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/pyAsyncPrologixGpib/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FPatrickBaus%2FpyAsyncPrologixGpib%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/pyAsyncPrologixGpib/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.