<?php
namespace app\plugins\nursery\service;

use think\facade\Db;

/** Append-only audit records for public price and shelf mutations. */
class GoodsAuditService
{
    private static $pending_save = [];

    public static function PrepareSave($goods_id, $params = [])
    {
        $goods_id = intval($goods_id);
        if($goods_id <= 0)
        {
            return null;
        }
        // A worker may process more than one request in the same PHP process.
        // Never let an aborted prior transaction leak a snapshot into a new
        // save; the ShopXO save path commits one goods row at a time.
        self::$pending_save = [];
        $admin_id = self::AdminId($params);
        if($admin_id <= 0)
        {
            throw new \RuntimeException('商品操作缺少管理员身份，无法写入审计');
        }
        $old = Db::name('Goods')->where(['id'=>$goods_id])
            ->field('id,is_shelves,price,min_price,max_price')->lock(true)->find();
        if(empty($old))
        {
            throw new \RuntimeException('商品不存在，无法写入操作审计');
        }
        self::$pending_save[$goods_id] = [
            'admin_id'  => $admin_id,
            'old'       => self::Summary($old, $goods_id),
            'old_shelf' => intval($old['is_shelves'] ?? 0),
            'reason'    => self::Reason($params),
            'request_id'=> self::RequestId($params),
        ];
        return null;
    }

    public static function CommitSave($goods_id, $params = [])
    {
        $goods_id = intval($goods_id);
        if($goods_id <= 0)
        {
            return null;
        }
        $pending = self::$pending_save[$goods_id] ?? null;
        unset(self::$pending_save[$goods_id]);
        if(!is_array($pending))
        {
            return null;
        }
        $current = Db::name('Goods')->where(['id'=>$goods_id])
            ->field('id,is_shelves,price,min_price,max_price')->lock(true)->find();
        if(empty($current))
        {
            throw new \RuntimeException('商品保存后无法读取审计摘要');
        }
        $new_summary = self::Summary($current, $goods_id);
        $admin_id = intval($pending['admin_id']);
        $reason = (string) ($pending['reason'] ?? '');
        $request_id = (string) ($pending['request_id'] ?? '');
        if((string) $pending['old']['price_summary'] !== (string) $new_summary['price_summary'])
        {
            self::Append($goods_id, $admin_id, 'price_update', $pending['old']['price_summary'], $new_summary['price_summary'], $reason, $request_id);
        }
        $old_shelf = intval($pending['old_shelf'] ?? 0);
        $new_shelf = intval($current['is_shelves'] ?? 0);
        if($old_shelf !== $new_shelf)
        {
            self::Append($goods_id, $admin_id, 'shelf_update', (string) $old_shelf, (string) $new_shelf, $reason, $request_id);
        }
        return null;
    }

    public static function RecordStatus($params, $previous_goods, $new_state)
    {
        if(!is_array($params) || (string) ($params['field'] ?? '') !== 'is_shelves')
        {
            return null;
        }
        if(!is_array($previous_goods) || intval($previous_goods['id'] ?? 0) <= 0)
        {
            throw new \RuntimeException('上下架审计缺少更新前商品状态');
        }
        $goods_id = intval($previous_goods['id']);
        $old_state = intval($previous_goods['is_shelves'] ?? 0);
        $new_state = intval($new_state);
        if($old_state === $new_state)
        {
            return null;
        }
        $admin_id = self::AdminId($params);
        if($admin_id <= 0)
        {
            throw new \RuntimeException('上下架操作缺少管理员身份，无法写入审计');
        }
        self::Append(
            $goods_id,
            $admin_id,
            'shelf_update',
            (string) $old_state,
            (string) $new_state,
            self::Reason($params),
            self::RequestId($params)
        );
        return null;
    }

    public static function AdminId($params)
    {
        return is_array($params) && is_array($params['admin'] ?? null) ? intval($params['admin']['id'] ?? 0) : 0;
    }

    private static function Summary($goods, $goods_id)
    {
        $prices = Db::name('GoodsSpecBase')->where(['goods_id'=>intval($goods_id)])
            ->order('id asc')->column('price');
        $normalized = [];
        foreach($prices as $price)
        {
            $normalized[] = self::Price((string) $price);
        }
        sort($normalized, SORT_STRING);
        $summary = [
            'price'      => self::Price($goods['price'] ?? ''),
            'min_price'  => self::Price($goods['min_price'] ?? ''),
            'max_price'  => self::Price($goods['max_price'] ?? ''),
            'spec_prices'=> $normalized,
        ];
        $encoded = json_encode($summary, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_PRESERVE_ZERO_FRACTION);
        if($encoded === false)
        {
            throw new \RuntimeException('商品价格审计摘要编码失败');
        }
        return ['price_summary'=>$encoded];
    }

    private static function Price($value)
    {
        $value = is_string($value) ? trim($value) : (string) $value;
        if(preg_match('/^[0-9]{1,8}(?:\.[0-9]{1,2})?$/D', $value) !== 1)
        {
            return '';
        }
        if(strpos($value, '.') === false)
        {
            return $value.'.00';
        }
        [$whole, $fraction] = explode('.', $value, 2);
        return $whole.'.'.str_pad($fraction, 2, '0');
    }

    private static function Append($goods_id, $admin_id, $action, $old_value, $new_value, $reason, $request_id)
    {
        // Audit is a write gate: a missing or drifted security schema must
        // abort the enclosing goods transaction rather than silently commit.
        SecurityMigration::AssertReady();
        $data = [
            'goods_id'  => intval($goods_id),
            'admin_id'  => intval($admin_id),
            'action'    => (string) $action,
            'old_value' => (string) $old_value,
            'new_value' => (string) $new_value,
            'reason'    => self::CleanText($reason, 255),
            'request_id'=> self::CleanText($request_id, 64),
            'add_time'  => time(),
        ];
        if(Db::name('PluginsNurseryGoodsAudit')->insertGetId($data) <= 0)
        {
            throw new \RuntimeException('商品操作审计写入失败');
        }
    }

    private static function Reason($params)
    {
        if(!is_array($params))
        {
            return '';
        }
        $value = $params['audit_reason'] ?? ($params['reason'] ?? '');
        return is_scalar($value) ? (string) $value : '';
    }

    private static function RequestId($params)
    {
        $value = is_array($params) ? ($params['request_id'] ?? '') : '';
        if(is_string($value) && preg_match('/^[A-Za-z0-9._:-]{1,64}$/D', $value) === 1)
        {
            return $value;
        }
        try {
            $header = request()->header('X-Request-Id');
            if(is_string($header) && preg_match('/^[A-Za-z0-9._:-]{1,64}$/D', $header) === 1)
            {
                return $header;
            }
        } catch(\Throwable $e) {
            // CLI/queue contexts have no request object.
        }
        return 'auto-'.bin2hex(random_bytes(8));
    }

    private static function CleanText($value, $max)
    {
        $value = is_scalar($value) ? (string) $value : '';
        $value = preg_replace('/[\x00-\x1F\x7F]/', ' ', $value);
        return function_exists('mb_substr') ? mb_substr($value, 0, $max, 'UTF-8') : substr($value, 0, $max);
    }
}
?>
