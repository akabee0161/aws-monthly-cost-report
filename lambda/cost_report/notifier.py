"""SNS への通知。

SNS の Subject は「ASCII テキスト」「改行・制御文字なし」「100文字未満」という制約がある。
制約違反は InvalidParameter となり Publish 自体が失敗するため、送信直前に必ずサニタイズする。
"""

MAX_SUBJECT_LENGTH = 99
_ELLIPSIS = "..."


def sanitize_subject(subject: str) -> str:
    """SNS の Subject 制約を満たす文字列に変換する。"""
    characters = []
    for char in subject:
        code = ord(char)
        if char in ("\n", "\r", "\t") or code < 0x20 or code == 0x7F:
            characters.append(" ")
        elif code > 0x7F:
            characters.append("?")
        else:
            characters.append(char)

    sanitized = "".join(characters).strip()
    if len(sanitized) <= MAX_SUBJECT_LENGTH:
        return sanitized
    return sanitized[: MAX_SUBJECT_LENGTH - len(_ELLIPSIS)] + _ELLIPSIS


def publish(client, topic_arn: str, subject: str, message: str) -> None:
    """SNS トピックへメッセージを送信する。"""
    client.publish(
        TopicArn=topic_arn,
        Subject=sanitize_subject(subject),
        Message=message,
    )
