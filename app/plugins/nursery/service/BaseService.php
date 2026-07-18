<?php
namespace app\plugins\nursery\service;

class BaseService
{
    public static function AdminPowerMenu()
    {
        return [
            [
                'name'    => '询价管理',
                'control' => 'inquiry',
                'action'  => 'index',
                'item'    => [
                    ['name'=>'查看询价详情', 'action'=>'detail'],
                    ['name'=>'回复询价', 'action'=>'reply'],
                    ['name'=>'更新询价状态', 'action'=>'statusupdate'],
                    ['name'=>'查看完整手机号', 'action'=>'contactreveal'],
                    ['name'=>'重开已结束询价', 'action'=>'reopen'],
                ],
            ],
        ];
    }
}
?>
