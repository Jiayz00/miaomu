<?php
namespace app\plugins\nursery\service;

class InquiryStateMachine
{
    public const PENDING = 'pending';
    public const REPLIED = 'replied';
    public const USER_VIEWED = 'user_viewed';
    public const COMMUNICATING = 'communicating';
    public const COMPLETED = 'completed';
    public const CLOSED = 'closed';

    private const LABELS = [
        self::PENDING       => '待处理',
        self::REPLIED       => '已回复',
        self::USER_VIEWED   => '用户已查看',
        self::COMMUNICATING => '沟通中',
        self::COMPLETED     => '已完成',
        self::CLOSED        => '已关闭',
    ];

    private const REPLY_FROM = [
        self::PENDING,
        self::REPLIED,
        self::USER_VIEWED,
        self::COMMUNICATING,
    ];

    private const ADMIN_TRANSITIONS = [
        self::PENDING       => [self::CLOSED],
        self::REPLIED       => [self::COMMUNICATING, self::COMPLETED, self::CLOSED],
        self::USER_VIEWED   => [self::COMMUNICATING, self::COMPLETED, self::CLOSED],
        self::COMMUNICATING => [self::COMPLETED, self::CLOSED],
        self::COMPLETED     => [],
        self::CLOSED        => [],
    ];

    public static function All()
    {
        return array_keys(self::LABELS);
    }

    public static function Labels()
    {
        return self::LABELS;
    }

    public static function Label($status)
    {
        return self::LABELS[$status] ?? '未知状态';
    }

    public static function IsValid($status)
    {
        return is_string($status) && array_key_exists($status, self::LABELS);
    }

    public static function IsTerminal($status)
    {
        return in_array($status, [self::COMPLETED, self::CLOSED], true);
    }

    public static function ReplyTarget($current)
    {
        if(!in_array($current, self::REPLY_FROM, true))
        {
            throw new \DomainException('当前询价状态不允许追加回复');
        }
        return self::REPLIED;
    }

    public static function IsAdminTransitionAllowed($from, $to)
    {
        return self::IsValid($from) && self::IsValid($to) && in_array($to, self::ADMIN_TRANSITIONS[$from], true);
    }

    public static function AssertAdminTransition($from, $to)
    {
        if(!self::IsAdminTransitionAllowed($from, $to))
        {
            throw new \DomainException('询价状态流转不合法');
        }
    }

    public static function UserViewTarget($current)
    {
        return ($current === self::REPLIED) ? self::USER_VIEWED : $current;
    }

    public static function AssertReopen($from, $reason)
    {
        if(!self::IsTerminal($from))
        {
            throw new \DomainException('只有已完成或已关闭询价可以重开');
        }
        if(!is_string($reason) || trim($reason) === '')
        {
            throw new \DomainException('重开询价必须填写原因');
        }
        return self::COMMUNICATING;
    }
}
?>
