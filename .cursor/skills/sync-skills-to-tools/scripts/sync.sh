#!/usr/bin/env bash
# sync.sh - 将 ~/.claude/skills/ 同步到 WorkBuddy、CodeBuddy、Cursor 项目 .cursor/skills/；
#           将 ~/.claude/agents/ 同步到 Cursor 项目 .cursor/agents/（供 Cloud Agent 使用）；
#           将 ~/.claude-internal/{skills,agents,knowledge} 软链到 ~/.claude 下对应目录（不 rsync）
# 用法:
#   ./scripts/sync.sh [--pull-first] [--workbuddy-only | --codebuddy-only | --cursor-only]
#   ./scripts/sync.sh --symlinks-only   只检查/建立 ~/.claude-internal 下三处软链，不同步 WB/CB/Cursor
#   ./scripts/sync.sh --cursor-only --project /path/to/project
#   ./scripts/sync.sh --list-profiles
#   ./scripts/sync.sh --init-profile quant-ai --project /path/to/project
#   --pull-first  先从远程 git 拉取 claude-config（~/.claude）到最新，再执行同步

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_PROFILE_PY="$SCRIPT_DIR/sync_cursor_profile.py"

CLAUDE_SKILLS="$HOME/.claude/skills"
CLAUDE_AGENTS="$HOME/.claude/agents"
CLAUDE_KNOWLEDGE="$HOME/.claude/knowledge"
INTERNAL_SKILLS="$HOME/.claude-internal/skills"
INTERNAL_AGENTS="$HOME/.claude-internal/agents"
INTERNAL_KNOWLEDGE="$HOME/.claude-internal/knowledge"
WORKBUDDY_SKILLS="$HOME/.workbuddy/skills"
CODEBUDDY_SKILLS="$HOME/.codebuddy/skills"
# 逗号分隔的 Git 项目根目录；skills/agents 同步到各仓库 .cursor/ 下（供 Cloud Agent 使用）
CURSOR_PROJECT_ROOTS="${CURSOR_PROJECT_ROOTS:-/Users/pengchao/hanzi/hanzi-cursor}"

PULL_FIRST=false
SYNC_TARGET="all"
SYMLINKS_ONLY=false
LIST_PROFILES=false
INIT_PROFILE=""
PROJECT_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pull-first|--pull) PULL_FIRST=true; shift ;;
        --workbuddy-only) SYNC_TARGET="workbuddy"; shift ;;
        --codebuddy-only) SYNC_TARGET="codebuddy"; shift ;;
        --cursor-only) SYNC_TARGET="cursor"; shift ;;
        --symlinks-only) SYMLINKS_ONLY=true; shift ;;
        --list-profiles) LIST_PROFILES=true; shift ;;
        --init-profile)
            INIT_PROFILE="${2:-}"
            [[ -n "$INIT_PROFILE" ]] || { echo "错误：--init-profile 需要 profile 名" >&2; exit 1; }
            shift 2
            ;;
        --project)
            PROJECT_PATH="${2:-}"
            [[ -n "$PROJECT_PATH" ]] || { echo "错误：--project 需要项目路径" >&2; exit 1; }
            shift 2
            ;;
        *)
            echo "未知参数: $1" >&2
            echo "用法: $0 [--pull-first] [--workbuddy-only | --codebuddy-only | --cursor-only | --symlinks-only | --list-profiles | --init-profile NAME [--project PATH] | --project PATH]" >&2
            exit 1
            ;;
    esac
done

if [[ "$LIST_PROFILES" == true ]]; then
    python3 "$SYNC_PROFILE_PY" list-profiles
    exit 0
fi

if [[ -n "$INIT_PROFILE" ]]; then
    target="${PROJECT_PATH:-.}"
    python3 "$SYNC_PROFILE_PY" init-profile "$INIT_PROFILE" "$target"
    exit 0
fi

if [[ "$SYMLINKS_ONLY" == true ]] && [[ "$PULL_FIRST" == true || "$SYNC_TARGET" != "all" || -n "$PROJECT_PATH" ]]; then
    echo "错误：--symlinks-only 不能与 --pull-first / --workbuddy-only / --codebuddy-only / --cursor-only / --project 同时使用" >&2
    exit 1
fi

git_pull_claude_config() {
    local claude_root
    claude_root="$(cd "$HOME/.claude" && pwd -P)"
    echo "Git 更新 claude-config ($claude_root) ..."
    if [[ ! -d "$claude_root/.git" ]]; then
        echo "警告：$claude_root 不是 git 仓库，跳过 git pull" >&2
        echo ""
        return 0
    fi
    (
        cd "$claude_root"
        git pull --ff-only
    )
    echo ""
}

sync_to() {
    local dest="$1"
    local dest_name="$2"
    mkdir -p "$dest"

    local added=() updated=() deleted=() skipped_count=0

    local src_skill_list=""
    for dir in "$CLAUDE_SKILLS"/*/; do
        local skill_name
        skill_name=$(basename "$dir")
        if [[ -f "${dir}SKILL.md" ]]; then
            src_skill_list="${src_skill_list}${skill_name}"$'\n'
        elif find "$dir" -maxdepth 2 -name "SKILL.md" | grep -q .; then
            src_skill_list="${src_skill_list}${skill_name}"$'\n'
        fi
    done

    while IFS= read -r skill_name; do
        [[ -z "$skill_name" ]] && continue
        local dir="$CLAUDE_SKILLS/$skill_name/"
        local target_dir="$dest/$skill_name"
        if [[ -L "$target_dir" ]]; then
            rm -f "$target_dir"
        fi
        if [[ ! -d "$target_dir" ]]; then
            rsync -aL "$dir" "$target_dir/"
            added+=("$skill_name")
        else
            local changed
            changed=$(rsync -aL --update --itemize-changes "$dir" "$target_dir/" | grep -c '^[<>]' || true)
            if [[ "$changed" -gt 0 ]]; then
                updated+=("$skill_name")
            else
                (( skipped_count++ )) || true
            fi
        fi
    done <<< "$src_skill_list"

    for target_dir in "$dest"/*/; do
        [[ ! -d "$target_dir" ]] && continue
        local skill_name
        skill_name=$(basename "$target_dir")
        if ! find "$target_dir" -maxdepth 2 -name "SKILL.md" | grep -q .; then
            continue
        fi
        if ! echo "$src_skill_list" | grep -qx "$skill_name"; then
            rm -rf "$target_dir"
            deleted+=("$skill_name")
        fi
    done

    local total
    total=$(find "$dest" -maxdepth 2 -name "SKILL.md" | wc -l | tr -d ' ')

    echo "$dest_name ($dest)："
    [[ ${#added[@]} -gt 0 ]] && echo "  新增（${#added[@]}）：${added[*]}"
    [[ ${#updated[@]} -gt 0 ]] && echo "  更新（${#updated[@]}）：${updated[*]}"
    [[ ${#deleted[@]} -gt 0 ]] && echo "  删除（${#deleted[@]}）：${deleted[*]}"
    echo "  跳过（已最新）：$skipped_count 个"
    echo "  目标共 $total 个技能"
}

ensure_internal_claude_symlinks() {
    echo "claude-internal（软链 -> ~/.claude，无复制）："
    mkdir -p "$HOME/.claude-internal"

    _ensure_link() {
        local label="$1" src="$2" dest="$3"
        if [[ ! -e "$src" ]]; then
            echo "  ${label}：跳过（源不存在：${src}）"
            return 0
        fi
        local abs_src
        abs_src=$(cd "$src" && pwd -P)

        if [[ -L "$dest" ]]; then
            local cur
            cur=$(readlink "$dest")
            if [[ "$cur" == "$abs_src" ]]; then
                echo "  ${label}：已是正确软链 -> ${abs_src}"
                return 0
            fi
            echo "  ${label}：移除旧软链后重建（${cur} -> ${abs_src}）"
            rm -f "$dest"
        elif [[ -e "$dest" ]]; then
            local bak
            bak="${dest}.pre-symlink.$(date +%Y%m%d%H%M%S)"
            echo "  ${label}：原路径为实体目录/文件，已改名为 ${bak} ，再建软链"
            mv "$dest" "$bak"
        fi
        ln -s "$abs_src" "$dest"
        echo "  ${label}：已 ln -s ${dest} -> ${abs_src}"
    }

    _ensure_link "skills" "$CLAUDE_SKILLS" "$INTERNAL_SKILLS"
    _ensure_link "agents" "$CLAUDE_AGENTS" "$INTERNAL_AGENTS"
    _ensure_link "knowledge" "$CLAUDE_KNOWLEDGE" "$INTERNAL_KNOWLEDGE"
}

sync_cursor_projects() {
    local roots_csv="$1"
    local root

    if [[ -n "$PROJECT_PATH" ]]; then
        roots_csv="$PROJECT_PATH"
    fi

    IFS=',' read -ra _cursor_roots <<< "$roots_csv"
    for root in "${_cursor_roots[@]}"; do
        root="${root#"${root%%[![:space:]]*}"}"
        root="${root%"${root##*[![:space:]]}"}"
        [[ -z "$root" ]] && continue
        if [[ ! -d "$root" ]]; then
            echo "Cursor 项目（跳过，目录不存在）：$root" >&2
            continue
        fi
        python3 "$SYNC_PROFILE_PY" sync "$root"
        echo ""
    done
}

if [[ "$SYMLINKS_ONLY" == true ]]; then
    ensure_internal_claude_symlinks
    echo ""
    echo "仅软链步骤完成 ✓"
    exit 0
fi

[[ "$PULL_FIRST" == true ]] && git_pull_claude_config

echo "同步开始..."
echo ""

[[ "$SYNC_TARGET" == "all" || "$SYNC_TARGET" == "workbuddy" ]] && sync_to "$WORKBUDDY_SKILLS" "WorkBuddy"
[[ "$SYNC_TARGET" == "all" || "$SYNC_TARGET" == "codebuddy" ]] && sync_to "$CODEBUDDY_SKILLS" "CodeBuddy"
if [[ "$SYNC_TARGET" == "all" || "$SYNC_TARGET" == "cursor" ]]; then
    sync_cursor_projects "$CURSOR_PROJECT_ROOTS"
fi

echo ""
ensure_internal_claude_symlinks

echo ""
total_src=$(find "$CLAUDE_SKILLS" -type f -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
total_agents=$(find "$CLAUDE_AGENTS" -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
echo "同步完成 ✓（源共 ${total_src} 个 SKILL.md、${total_agents} 个 agent .md；internal 三目录已保证为 ~/.claude 的软链）"
