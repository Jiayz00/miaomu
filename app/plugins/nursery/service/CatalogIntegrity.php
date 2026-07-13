<?php
namespace app\plugins\nursery\service;

use think\facade\Db;

class CatalogIntegrity
{
    public const AUDIT_TAG = 'plugins_nursery_catalog_integrity_log';
    private const EXECUTION_LOCK = 'shopxo_nursery_catalog_integrity';
    private const MAX_REVIEW_ITEMS = 500;

    public static function Run($apply = false, $actor = '', $run_id = '', $expected_items_sha256 = '')
    {
        if($apply !== true)
        {
            try {
                $items = self::AnalyzePublishedGoods(false);
                return DataReturn('苗木公开价格完整性 dry-run 完成', 0, [
                    'apply'           => false,
                    'write_performed' => false,
                    'count'           => count($items),
                    'truncated'       => count($items) > self::MAX_REVIEW_ITEMS,
                    'items_sha256'    => self::ItemsHash($items),
                    'items'           => array_slice($items, 0, self::MAX_REVIEW_ITEMS),
                ]);
            } catch(\Throwable $e) {
                return DataReturn($e->getMessage(), -1);
            }
        }

        try {
            self::ValidateExecutionMetadata($actor, $run_id);
            if(!is_string($expected_items_sha256) || preg_match('/^[a-f0-9]{64}$/D', $expected_items_sha256) !== 1)
            {
                throw new \InvalidArgumentException('价格完整性 apply 必须提供有效的 dry-run items_sha256');
            }
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }

        $lock_connection = null;
        $transaction_started = false;
        try {
            $lock_connection = self::AcquireExecutionLock();
            $lock_connection->startTrans();
            $transaction_started = true;
            $audit_row = Db::name('Config')->where(['only_tag'=>self::AUDIT_TAG])->lock(true)->field('id,value')->find();
            $audit = self::DecodeAudit(empty($audit_row) ? '' : $audit_row['value']);
            $previous_run = self::FindRun($audit, $run_id);
            if($previous_run !== null)
            {
                if(!isset($previous_run['actor'], $previous_run['reviewed_items_sha256']) || (string) $previous_run['actor'] !== $actor || !hash_equals((string) $previous_run['reviewed_items_sha256'], $expected_items_sha256))
                {
                    throw new \RuntimeException('该价格完整性 run-id 已绑定其他操作者或审查清单');
                }
                $lock_connection->commit();
                $transaction_started = false;
                return DataReturn('价格完整性修复已执行过该 run-id', 0, [
                    'apply'           => true,
                    'write_performed' => false,
                    'replayed'        => true,
                    'count'           => intval(isset($previous_run['count']) ? $previous_run['count'] : 0),
                    'items_sha256'    => (string) $previous_run['reviewed_items_sha256'],
                ]);
            }

            $items = self::AnalyzePublishedGoods(true);
            if(count($items) > self::MAX_REVIEW_ITEMS)
            {
                throw new \RuntimeException('价格完整性修复项超过单次审查上限，请先分批处理后重试');
            }
            $reviewed_hash = self::ItemsHash($items);
            if(!hash_equals($expected_items_sha256, $reviewed_hash))
            {
                throw new \RuntimeException('价格完整性清单已变化，请重新执行 dry-run 并审查');
            }
            foreach($items as &$item)
            {
                $upd_time = time();
                $item['after']['upd_time'] = $upd_time;
                if($item['action'] === 'downlist')
                {
                    $updated = Db::name('Goods')->where(['id'=>intval($item['goods_id']), 'is_shelves'=>1])->update([
                        'is_shelves' => 0,
                        'upd_time'   => $upd_time,
                    ]);
                } else {
                    $updated = Db::name('Goods')->where(['id'=>intval($item['goods_id']), 'is_shelves'=>1])->update([
                        'min_price' => $item['after']['min_price'],
                        'max_price' => $item['after']['max_price'],
                        'price'     => $item['after']['price'],
                        'upd_time'  => $upd_time,
                    ]);
                }
                if($updated !== 1)
                {
                    throw new \RuntimeException('价格完整性修复遇到并发变化，商品 ID：'.$item['goods_id']);
                }
                $item['applied'] = true;
            }
            unset($item);

            $applied_at = time();
            $run_summary = [
                'run_id'     => $run_id,
                'actor'      => $actor,
                'applied_at' => $applied_at,
                'count'      => count($items),
                'reviewed_items_sha256' => $reviewed_hash,
                'applied_items_sha256'  => self::ItemsHash($items),
            ];
            $audit['history'][] = $run_summary;
            $audit['runs'][] = array_merge($run_summary, [
                'items'      => $items,
            ]);
            if(count($audit['runs']) > 20)
            {
                $audit['runs'] = array_slice($audit['runs'], -20);
            }
            self::WriteAudit(empty($audit_row) ? null : intval($audit_row['id']), $audit);
            $lock_connection->commit();
            $transaction_started = false;
            return DataReturn('苗木公开价格完整性修复完成', 0, [
                'apply'           => true,
                'write_performed' => !empty($items),
                'replayed'        => false,
                'count'           => count($items),
                'truncated'       => false,
                'items_sha256'    => self::ItemsHash($items),
                'items'           => $items,
            ]);
        } catch(\Throwable $e) {
            if($transaction_started)
            {
                try {
                    $lock_connection->rollback();
                } catch(\Throwable $rollback_error) {
                }
            }
            return DataReturn($e->getMessage(), -1);
        } finally {
            if($lock_connection !== null)
            {
                self::ReleaseExecutionLock($lock_connection);
            }
        }
    }

    private static function AnalyzePublishedGoods($lock)
    {
        $query = Db::name('Goods')->where(['is_shelves'=>1, 'is_delete_time'=>0])->field('id,is_shelves,min_price,max_price,price,upd_time')->order('id asc');
        if($lock)
        {
            $query->lock(true);
        }
        $goods = $query->select()->toArray();
        if(empty($goods))
        {
            return [];
        }

        $spec_query = Db::name('GoodsSpecBase')->where('goods_id', 'in', array_column($goods, 'id'))->field('goods_id,price')->order('goods_id asc,id asc');
        if($lock)
        {
            $spec_query->lock(true);
        }
        $spec_rows = $spec_query->select()->toArray();
        $spec_group = [];
        foreach($spec_rows as $spec)
        {
            $spec_group[intval($spec['goods_id'])][] = $spec['price'];
        }

        $items = [];
        foreach($goods as $item)
        {
            $goods_id = intval($item['id']);
            $prices = isset($spec_group[$goods_id]) ? $spec_group[$goods_id] : [];
            $before = [
                'is_shelves' => intval($item['is_shelves']),
                'min_price'  => (string) $item['min_price'],
                'max_price'  => (string) $item['max_price'],
                'price'      => (string) $item['price'],
                'upd_time'   => intval($item['upd_time']),
            ];
            if(empty($prices))
            {
                $items[] = [
                    'goods_id' => $goods_id,
                    'action'   => 'downlist',
                    'reasons'  => ['missing_spec_price'],
                    'before'   => $before,
                    'after'    => array_merge($before, ['is_shelves'=>0, 'upd_time'=>null]),
                    'applied'  => false,
                ];
                continue;
            }

            $cents = [];
            foreach($prices as $price)
            {
                $value = ReferencePriceService::StoredPriceToCents($price);
                if($value === null || $value < 1 || $value > ReferencePriceService::MAX_PRICE_CENTS)
                {
                    $cents = [];
                    break;
                }
                $cents[] = $value;
            }
            if(empty($cents))
            {
                $items[] = [
                    'goods_id' => $goods_id,
                    'action'   => 'downlist',
                    'reasons'  => ['invalid_spec_price'],
                    'before'   => $before,
                    'after'    => array_merge($before, ['is_shelves'=>0, 'upd_time'=>null]),
                    'applied'  => false,
                ];
                continue;
            }

            $min = min($cents);
            $max = max($cents);
            $expected = [
                'is_shelves' => 1,
                'min_price'  => ReferencePriceService::FormatCents($min),
                'max_price'  => ReferencePriceService::FormatCents($max),
                'price'      => ReferencePriceService::FormatCents($min).(($min === $max) ? '' : '-'.ReferencePriceService::FormatCents($max)),
                'upd_time'   => null,
            ];
            if(ReferencePriceService::StoredPriceToCents($item['min_price']) !== $min || ReferencePriceService::StoredPriceToCents($item['max_price']) !== $max || (string) $item['price'] !== $expected['price'])
            {
                $items[] = [
                    'goods_id' => $goods_id,
                    'action'   => 'recalculate',
                    'reasons'  => ['derived_summary_drift'],
                    'before'   => $before,
                    'after'    => $expected,
                    'applied'  => false,
                ];
            }
        }
        return $items;
    }

    private static function DecodeAudit($value)
    {
        if(empty($value))
        {
            return ['schema_version'=>1, 'history'=>[], 'runs'=>[]];
        }
        $audit = json_decode($value, true);
        if(!is_array($audit) || intval($audit['schema_version']) !== 1 || !isset($audit['runs']) || !is_array($audit['runs']))
        {
            throw new \RuntimeException('苗木价格完整性审计台账无效');
        }
        if(!isset($audit['history']) || !is_array($audit['history']))
        {
            $audit['history'] = [];
            foreach($audit['runs'] as $run)
            {
                if(isset($run['run_id']))
                {
                    $audit['history'][] = [
                        'run_id'     => $run['run_id'],
                        'actor'      => isset($run['actor']) ? $run['actor'] : '',
                        'applied_at' => isset($run['applied_at']) ? intval($run['applied_at']) : 0,
                        'count'      => isset($run['count']) ? intval($run['count']) : 0,
                    ];
                }
            }
        }
        return $audit;
    }

    private static function FindRun($audit, $run_id)
    {
        if(empty($audit['history']) || !is_array($audit['history']))
        {
            return null;
        }
        foreach(array_reverse($audit['history']) as $run)
        {
            if(is_array($run) && isset($run['run_id']) && $run['run_id'] === $run_id)
            {
                return $run;
            }
        }
        return null;
    }

    private static function ItemsHash($items)
    {
        $value = json_encode($items, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        if($value === false)
        {
            throw new \RuntimeException('价格完整性修复清单编码失败');
        }
        return hash('sha256', $value);
    }

    private static function WriteAudit($id, $audit)
    {
        $value = json_encode($audit, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        if($value === false)
        {
            throw new \RuntimeException('苗木价格完整性审计编码失败');
        }
        if(empty($id))
        {
            $id = Db::name('Config')->insertGetId([
                'value'      => $value,
                'name'       => '苗木价格完整性审计',
                'describe'   => '公开价格 dry-run/apply 修复的非敏感审计摘要',
                'error_tips' => '',
                'type'       => 'common',
                'only_tag'   => self::AUDIT_TAG,
                'upd_time'   => time(),
            ]);
            if($id <= 0)
            {
                throw new \RuntimeException('苗木价格完整性审计写入失败');
            }
        } elseif(Db::name('Config')->where(['id'=>intval($id), 'only_tag'=>self::AUDIT_TAG])->update(['value'=>$value, 'upd_time'=>time()]) === false) {
            throw new \RuntimeException('苗木价格完整性审计更新失败');
        }
    }

    private static function ValidateExecutionMetadata($actor, $run_id)
    {
        if(!is_string($actor) || preg_match('/^[A-Za-z0-9._:@\/-]{2,80}$/D', $actor) !== 1)
        {
            throw new \InvalidArgumentException('价格完整性 apply actor 格式无效');
        }
        if(!is_string($run_id) || preg_match('/^[A-Za-z0-9][A-Za-z0-9._:-]{5,100}$/D', $run_id) !== 1)
        {
            throw new \InvalidArgumentException('价格完整性 apply run-id 格式无效');
        }
    }

    private static function AcquireExecutionLock()
    {
        $connection = Db::connect();
        $rows = $connection->query("SELECT GET_LOCK('".self::EXECUTION_LOCK."', 30) AS acquired", [], true);
        if(empty($rows) || !isset($rows[0]['acquired']) || intval($rows[0]['acquired']) !== 1)
        {
            throw new \RuntimeException('无法获取价格完整性修复串行锁');
        }
        return $connection;
    }

    private static function ReleaseExecutionLock($connection)
    {
        $rows = $connection->query("SELECT RELEASE_LOCK('".self::EXECUTION_LOCK."') AS released", [], true);
        if(empty($rows) || !isset($rows[0]['released']) || intval($rows[0]['released']) !== 1)
        {
            throw new \RuntimeException('价格完整性修复已结束，但串行锁释放失败');
        }
    }
}
?>
