<?php
namespace app\plugins\nursery\service;

use think\facade\Db;

/**
 * Favorite writes have their own counter.  It intentionally does not share
 * the inquiry counter: saving a favorite and submitting an inquiry are
 * independent user actions with different abuse profiles.
 */
class FavoriteRateLimit
{
    public const WINDOW_SECONDS = 60;
    public const MAX_ATTEMPTS = 20;

    private const ACTIONS = ['add', 'cancel'];

    public static function Consume($user_id, $action)
    {
        $user_id = intval($user_id);
        if($user_id <= 0 || !is_string($action) || !in_array($action, self::ACTIONS, true))
        {
            throw new \InvalidArgumentException('收藏限流参数无效');
        }

        SecurityMigration::AssertReady();

        // A concurrent first request can race the composite primary key.  A
        // single retry turns that race into the same row-lock path.
        for($retry=0; $retry<2; $retry++)
        {
            $transaction_started = false;
            try {
                Db::startTrans();
                $transaction_started = true;
                $now = self::DatabaseNow();
                $row = Db::name('PluginsNurseryFavoriteRateLimit')
                    ->where(['user_id'=>$user_id, 'action'=>$action])
                    ->lock(true)
                    ->find();

                if(empty($row))
                {
                    try {
                        Db::name('PluginsNurseryFavoriteRateLimit')->insert([
                            'user_id'          => $user_id,
                            'action'           => $action,
                            'window_started_at'=> $now,
                            'attempt_count'    => 1,
                            'updated_at'       => $now,
                        ]);
                    } catch(\Throwable $insert_error) {
                        if(self::IsDuplicateKeyError($insert_error) && $retry === 0)
                        {
                            Db::rollback();
                            $transaction_started = false;
                            continue;
                        }
                        throw $insert_error;
                    }
                    Db::commit();
                    return [
                        'allowed'          => true,
                        'attempt_count'    => 1,
                        'remaining'        => self::MAX_ATTEMPTS-1,
                        'window_started_at'=> $now,
                    ];
                }

                $started_at = intval($row['window_started_at'] ?? 0);
                $count = intval($row['attempt_count'] ?? 0);
                if($started_at <= 0 || $now < $started_at || $count < 1 || $count > self::MAX_ATTEMPTS)
                {
                    throw new \RuntimeException('收藏频率限制状态无效');
                }
                if(($now - $started_at) >= self::WINDOW_SECONDS)
                {
                    $started_at = $now;
                    $count = 0;
                }
                if($count >= self::MAX_ATTEMPTS)
                {
                    Db::rollback();
                    $transaction_started = false;
                    throw new \RuntimeException('收藏操作过于频繁，请稍后再试');
                }

                $count++;
                $updated = Db::name('PluginsNurseryFavoriteRateLimit')
                    ->where(['user_id'=>$user_id, 'action'=>$action])
                    ->update([
                        'window_started_at'=> $started_at,
                        'attempt_count'    => $count,
                        'updated_at'       => $now,
                    ]);
                if($updated === false)
                {
                    throw new \RuntimeException('收藏频率限制写入失败');
                }
                Db::commit();
                return [
                    'allowed'          => true,
                    'attempt_count'    => $count,
                    'remaining'        => self::MAX_ATTEMPTS-$count,
                    'window_started_at'=> $started_at,
                ];
            } catch(\Throwable $e) {
                if($transaction_started)
                {
                    try { Db::rollback(); } catch(\Throwable $rollback_error) { /* preserve primary error */ }
                }
                throw $e;
            }
        }

        throw new \RuntimeException('收藏频率限制暂时不可用');
    }

    private static function DatabaseNow()
    {
        $rows = Db::query('SELECT UNIX_TIMESTAMP() AS now');
        $now = intval($rows[0]['now'] ?? 0);
        if($now <= 0)
        {
            throw new \RuntimeException('收藏频率限制时间源不可用');
        }
        return $now;
    }

    private static function IsDuplicateKeyError($error)
    {
        $code = (string) $error->getCode();
        $message = (string) $error->getMessage();
        return $code === '1062' || strpos($message, 'Duplicate entry') !== false || strpos($message, '1062') !== false;
    }
}
?>
