<?php
namespace app\plugins\nursery\service;

use think\facade\Db;
use app\service\UserService;
use app\service\ResourcesService;

class FavoriteService
{
    private const NONCE_SESSION_KEY = 'nursery_favorite_nonce_v1';
    private const MAX_GOODS_ID = 4294967295;

    public static function Add($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            $goods_id = self::StrictGoodsId($params);
            FavoriteMigration::AssertReady();
            self::AssertGoodsCanBeFavorited($goods_id);
            try {
                $inserted = Db::name('GoodsFavor')->insert([
                    'goods_id' => $goods_id,
                    'user_id'  => $user_id,
                    'add_time' => time(),
                ]);
                if($inserted !== 1)
                {
                    throw new \RuntimeException('收藏写入失败');
                }
            } catch(\Throwable $write_error) {
                if(!self::IsDuplicateKeyError($write_error) || !self::OwnPairExists($user_id, $goods_id))
                {
                    throw $write_error;
                }
            }
            return self::StateResponse($goods_id, true, '收藏成功');
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Cancel($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            $goods_id = self::StrictGoodsId($params);
            $deleted = Db::name('GoodsFavor')->where(['user_id'=>$user_id, 'goods_id'=>$goods_id])->delete();
            if($deleted === false)
            {
                throw new \RuntimeException('取消收藏失败');
            }
            return self::StateResponse($goods_id, false, '已取消收藏');
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Status($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            $goods_id = self::StrictGoodsId($params);
            return self::StateResponse($goods_id, self::OwnPairExists($user_id, $goods_id), '收藏状态读取成功');
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Listing($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            $page = self::PositivePage($params['page'] ?? 1, 1);
            $page_size = min(self::PositivePage($params['page_size'] ?? 12, 12), 50);
            $start = ($page-1)*$page_size;
            $total = intval(Db::name('GoodsFavor')->where(['user_id'=>$user_id])->count());
            $rows = Db::name('GoodsFavor')->alias('f')
                ->leftJoin('goods g', 'g.id=f.goods_id')
                ->where(['f.user_id'=>$user_id])
                ->field('f.goods_id,f.add_time,g.id AS goods_exists,g.title,g.images,g.price,g.min_price,g.max_price,g.inventory_unit,g.is_shelves,g.is_delete_time')
                ->order('f.id desc')
                ->limit($start, $page_size)
                ->select()
                ->toArray();
            foreach($rows as &$row)
            {
                $exists = !empty($row['goods_exists']);
                if(!$exists)
                {
                    $state = 'deleted';
                } elseif(intval($row['is_delete_time']) !== 0) {
                    $state = 'deleted';
                } elseif(intval($row['is_shelves']) !== 1) {
                    $state = 'off_shelf';
                } else {
                    $state = 'active';
                }
                if($exists)
                {
                    $row['show_price_symbol'] = ResourcesService::CurrencyDataSymbol();
                    ReferencePriceService::ApplyDisplay($row);
                    $row['images'] = empty($row['images']) ? '' : AttachmentPathViewHandle($row['images']);
                } else {
                    $row['title'] = '商品已删除';
                    $row['images'] = '';
                    $row['reference_price'] = null;
                }
                $row['goods_id'] = intval($row['goods_id']);
                $row['add_time'] = intval($row['add_time']);
                $row['favorite_time_text'] = empty($row['add_time']) ? '' : date('Y-m-d H:i', $row['add_time']);
                $row['availability'] = $state;
                $row['availability_text'] = self::AvailabilityText($state);
                $row['can_view'] = ($state === 'active');
                $row['goods_url'] = $row['can_view'] ? MyUrl('index/goods/index', ['id'=>$row['goods_id']]) : '';
                $row['inquiry_url'] = $row['can_view'] ? PluginsHomeUrl('nursery', 'inquiry', 'form', ['goods_id'=>$row['goods_id']]) : '';
                unset($row['goods_exists'], $row['price'], $row['min_price'], $row['max_price'], $row['inventory_unit'], $row['is_shelves'], $row['is_delete_time']);
            }
            unset($row);
            return DataReturn('收藏列表读取成功', 0, [
                'items'      => $rows,
                'total'      => $total,
                'page'       => $page,
                'page_size'  => $page_size,
                'page_total' => max(1, intval(ceil($total/$page_size))),
                'has_previous' => $page > 1,
                'previous_page'=> max(1, $page-1),
                'has_next'     => $page*$page_size < $total,
                'next_page'    => $page+1,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function WebRequestNonce()
    {
        $nonce = MySession(self::NONCE_SESSION_KEY);
        if(!is_string($nonce) || preg_match('/^[a-f0-9]{64}$/D', $nonce) !== 1)
        {
            $nonce = bin2hex(random_bytes(32));
            MySession(self::NONCE_SESSION_KEY, $nonce);
        }
        return $nonce;
    }

    public static function ValidateWebWrite($params = [])
    {
        if(!request()->isPost() || !IS_AJAX)
        {
            return DataReturn('收藏写操作仅接受站内异步 POST 请求', -1);
        }
        $provided = isset($params['request_nonce']) && is_string($params['request_nonce']) ? $params['request_nonce'] : '';
        $expected = MySession(self::NONCE_SESSION_KEY);
        if(!is_string($expected) || strlen($expected) !== 64 || strlen($provided) !== 64 || !hash_equals($expected, $provided))
        {
            return DataReturn('收藏请求校验失败，请刷新页面后重试', -1);
        }
        return DataReturn('success', 0);
    }

    private static function AuthenticatedUserId($user)
    {
        if(!is_array($user) || !isset($user['id']) || intval($user['id']) <= 0)
        {
            throw new \RuntimeException('请先登录后操作收藏');
        }
        $user_id = intval($user['id']);
        $status = UserService::UserStatusCheck($user_id);
        if(!is_array($status) || intval($status['code'] ?? -1) !== 0)
        {
            throw new \RuntimeException('当前用户状态不可用');
        }
        return $user_id;
    }

    private static function StrictGoodsId($params)
    {
        $value = $params['goods_id'] ?? null;
        if(is_int($value))
        {
            $valid = $value > 0 && $value <= self::MAX_GOODS_ID;
        } else {
            $valid = is_string($value) && preg_match('/^[1-9][0-9]*$/D', $value) === 1 && (strlen($value) < 10 || (strlen($value) === 10 && strcmp($value, (string) self::MAX_GOODS_ID) <= 0));
        }
        if(!$valid || intval($value) <= 0)
        {
            throw new \InvalidArgumentException('商品编号无效');
        }
        return intval($value);
    }

    private static function PositivePage($value, $default)
    {
        if(is_int($value))
        {
            return $value > 0 ? $value : $default;
        }
        if(is_string($value) && preg_match('/^[1-9][0-9]*$/D', $value) === 1)
        {
            return intval($value);
        }
        return $default;
    }

    private static function AssertGoodsCanBeFavorited($goods_id)
    {
        $goods = Db::name('Goods')->where(['id'=>$goods_id])->field('id,is_shelves,is_delete_time')->find();
        if(empty($goods) || intval($goods['is_delete_time']) !== 0 || intval($goods['is_shelves']) !== 1)
        {
            throw new \RuntimeException('该商品当前不可收藏');
        }
    }

    private static function OwnPairExists($user_id, $goods_id)
    {
        return Db::name('GoodsFavor')->where(['user_id'=>$user_id, 'goods_id'=>$goods_id])->count() > 0;
    }

    private static function IsDuplicateKeyError($error)
    {
        $code = (string) $error->getCode();
        $message = $error->getMessage();
        return $code === '1062' || ($code === '23000' && strpos($message, '1062') !== false) || strpos($message, 'Duplicate entry') !== false;
    }

    private static function StateResponse($goods_id, $active, $message)
    {
        return DataReturn($message, 0, [
            'goods_id' => intval($goods_id),
            'status'   => $active ? 1 : 0,
            'text'     => $active ? '已收藏' : '收藏',
        ]);
    }

    private static function AvailabilityText($state)
    {
        if($state === 'active')
        {
            return '可查看';
        }
        if($state === 'off_shelf')
        {
            return '已下架';
        }
        return '已删除';
    }
}
?>
