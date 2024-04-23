# Architecture decision record

*23.4.2024* **Own framework for testing in docker containers**

Decided that only viable alternative as of now is to use our own framework for creating containers from docker compose.

`testcontainers` (https://pypi.org/project/testcontainers/) was considered as an alternative, but while having several nice ideas, it seemed to have fairly similar approach with missing features for some of the things we needed, like streaming read and providing a user for `exec` commands.

Some nice ideas were adopted from the framework though.
