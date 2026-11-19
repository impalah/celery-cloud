#!/usr/bin/env bash
# Checks the Terraform code without credentials and without remote state:
#   1. terraform fmt -check -recursive
#   2. terraform init -backend=false + terraform validate, in every module and in the stack
#   3. terraform test (mocked AWS provider) in the stacks that have tests
set -euo pipefail

cd "$(dirname "$0")"

# Never let a validation touch a real account
for var in $(env | grep -o '^AWS_[A-Z_]*' || true); do unset "$var"; done

if ! command -v terraform >/dev/null; then
  echo "terraform is not installed" >&2
  exit 1
fi

echo "== terraform fmt"
terraform fmt -check -recursive

failed=0
for dir in modules/* stacks/*; do
  echo "== validate $dir"
  if ! (cd "$dir" && terraform init -backend=false -input=false -no-color >/dev/null && terraform validate -no-color); then
    failed=1
  fi
done

# Plan-level tests with a mocked provider (stacks that have .tftest.hcl files)
for dir in stacks/*; do
  if compgen -G "$dir/*.tftest.hcl" >/dev/null; then
    echo "== test $dir"
    if ! (cd "$dir" && terraform test -no-color); then
      failed=1
    fi
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "validation failed" >&2
  exit 1
fi
echo "OK"
