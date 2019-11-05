#!/usr/bin/env bash

usage(){
    echo "Usage: $0 [容器名] [镜像名] [CPU数] [内存大小] [宿主(可选)]"
    echo "Example: $0 ubuntu1 ubuntu:18.04 2 512MB"
    exit 2
}

trap 'exit 3' INT

if [[ -z $4 ]]; then
    usage
fi

name=$1
image=$2
core=$3
mem=$4
target_node=$5

if [[ -n $target_node ]]; then
    lxc launch $image $name --target $target_node
else
    lxc launch $image $name
fi

if [[ $? != 0 ]]; then
    exit 3
fi

lxc config set $name limits.cpu $core
lxc config set $name limits.memory $mem