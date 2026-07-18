<?php
namespace app\plugins\nursery\service;

use think\facade\Db;
use app\service\UserService;

class InquiryPublicException extends \RuntimeException
{
}

class InquiryService
{
    private const USER_NONCE_SESSION_KEY = 'nursery_inquiry_user_nonce_v1';
    private const ADMIN_NONCE_SESSION_KEY = 'nursery_inquiry_admin_nonce_v1';
    private const FINGERPRINT_VERSION = 'dup-v1';
    private const DUPLICATE_WINDOW_SECONDS = 600;
    private const RATE_WINDOW_SECONDS = 60;
    private const RATE_MAX_ATTEMPTS = 5;
    private const HMAC_ENV_KEY = 'nursery_inquiry_hmac_key';
    private const MAX_UINT32 = 4294967295;
    private const MAX_BIGINT = '9223372036854775807';

    public static function FormData($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            self::AssertReady();
            $goods_id = self::StrictUnsignedId($params['goods_id'] ?? null, '商品编号');
            $snapshot = self::PublishedGoodsSnapshot($goods_id, $params['spec_base_id'] ?? null, false);
            $profile = Db::name('User')->where(['id'=>$user_id])->field('id,username,nickname,mobile')->find();
            $region_rows = Db::name('Region')->where([['is_enable', '=', 1], ['level', 'in', [1, 2, 3]]])
                ->field('id,pid,name,level,code')
                ->order('level asc,sort asc,id asc')
                ->select()
                ->toArray();
            $regions = self::RegionOptionData($region_rows);
            return DataReturn('询价表单读取成功', 0, [
                'goods'          => self::PublicGoodsData($snapshot),
                'spec_options'   => $snapshot['spec_options'],
                'spec_base_id'   => empty($snapshot['selected_spec']) ? null : intval($snapshot['selected_spec']['base_id']),
                'region_options' => $regions,
                'defaults'       => [
                    'contact_name'  => self::PreferredUserName($profile),
                    'contact_phone' => is_array($profile) ? (string) ($profile['mobile'] ?? '') : '',
                    'quantity_unit' => $snapshot['reference_unit'],
                ],
            ]);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            return DataReturn('询价表单暂时无法读取，请稍后重试', -1);
        }
    }

    public static function RegionOptions()
    {
        try {
            self::AssertReady();
            return self::RegionOptionData();
        } catch(\Throwable $e) {
            return ['province'=>[], 'city'=>[], 'county'=>[]];
        }
    }

    public static function Submit($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            self::AssertReady();
            $validated = self::ValidateSubmission($user_id, $params);

            // The abuse counter commits before the duplicate/business transaction.
            self::ConsumeRateLimit($user_id);
            $created = self::CreateInquiry($user_id, $validated);
            return DataReturn('询价提交成功', 0, $created);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            return DataReturn('询价提交失败，请稍后重试', -1);
        }
    }

    public static function UserList($user, $params = [])
    {
        try {
            $user_id = self::AuthenticatedUserId($user);
            self::AssertReady();
            $page = self::PositivePage($params['page'] ?? 1, 1);
            $page_size = min(self::PositivePage($params['page_size'] ?? 12, 12), 50);
            $start = ($page-1)*$page_size;
            $where = ['user_id'=>$user_id];
            if(isset($params['status']) && $params['status'] !== '')
            {
                $status = self::StrictStatus($params['status']);
                $where['status'] = $status;
            }
            $total = intval(Db::name('PluginsNurseryInquiry')->where($where)->count());
            $items = Db::name('PluginsNurseryInquiry')
                ->where($where)
                ->field('id,inquiry_no,user_id,goods_id,goods_title,goods_images,reference_price,reference_min,reference_max,reference_unit,spec_snapshot,quantity,quantity_unit,region_province_name,region_city_name,region_county_name,status,first_replied_at,created_at,updated_at')
                ->order('id desc')
                ->limit($start, $page_size)
                ->select()
                ->toArray();
            foreach($items as &$item)
            {
                self::DecorateInquiryRow($item, false);
                $reply = Db::name('PluginsNurseryInquiryReply')
                    ->where(['inquiry_id'=>intval($item['id'])])
                    ->field('reply_note,created_at,valid_until,unit_price,total_amount')
                    ->order('id desc')
                    ->find();
                $item['latest_reply_note'] = empty($reply) ? '' : (string) ($reply['reply_note'] ?? '');
                $item['latest_reply_at'] = empty($reply['created_at'] ?? null) ? '' : (string) $reply['created_at'];
                $item['latest_reply_at_text'] = empty($reply['created_at'] ?? null) ? '' : date('Y-m-d H:i', strtotime((string) $reply['created_at']));
                $item['latest_reply_valid_until'] = empty($reply['valid_until'] ?? null) ? '' : (string) $reply['valid_until'];
                $item['latest_reply_unit_price'] = empty($reply['unit_price'] ?? null) ? '' : (string) $reply['unit_price'];
                $item['latest_reply_total_amount'] = empty($reply['total_amount'] ?? null) ? '' : (string) $reply['total_amount'];
            }
            unset($item);
            return DataReturn('我的询价读取成功', 0, self::PageData($items, $total, $page, $page_size));
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            return DataReturn('我的询价暂时无法读取，请稍后重试', -1);
        }
    }

    public static function UserDetail($user, $params = [])
    {
        $connection = null;
        $transaction_started = false;
        try {
            $user_id = self::AuthenticatedUserId($user);
            self::AssertReady();
            $inquiry_id = self::StrictInquiryId($params['inquiry_id'] ?? ($params['id'] ?? null));
            $connection = Db::connect();
            $connection->startTrans();
            $transaction_started = true;
            $inquiry = self::Table($connection, 'PluginsNurseryInquiry')
                ->where(['id'=>$inquiry_id, 'user_id'=>$user_id])
                ->lock(true)
                ->find();
            if(empty($inquiry))
            {
                throw new InquiryPublicException('询价记录不存在或不可访问');
            }
            if((string) $inquiry['status'] === InquiryStateMachine::REPLIED)
            {
                $clock = self::DatabaseClock($connection);
                $updated = self::Table($connection, 'PluginsNurseryInquiry')
                    ->where(['id'=>$inquiry_id, 'user_id'=>$user_id, 'status'=>InquiryStateMachine::REPLIED])
                    ->update(['status'=>InquiryStateMachine::USER_VIEWED, 'updated_at'=>$clock['datetime']]);
                if($updated !== 1)
                {
                    throw new \RuntimeException('用户查看状态并发更新失败');
                }
                self::AppendHistory([
                    'inquiry_id' => $inquiry_id,
                    'from_status'=> InquiryStateMachine::REPLIED,
                    'to_status'  => InquiryStateMachine::USER_VIEWED,
                    'actor_type' => 'user',
                    'actor_id'   => $user_id,
                    'actor_name' => '用户#'.$user_id,
                    'event_type' => 'user_viewed',
                    'reason'     => '用户首次查看管理员回复',
                    'reply_id'   => null,
                    'created_at' => $clock['datetime'],
                ], $connection);
                $inquiry['status'] = InquiryStateMachine::USER_VIEWED;
                $inquiry['updated_at'] = $clock['datetime'];
            }
            $connection->commit();
            $transaction_started = false;
            return self::DetailResponse($inquiry, true);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn('询价详情暂时无法读取，请稍后重试', -1);
        }
    }

    public static function AdminList($admin, $params = [])
    {
        try {
            self::AuthenticatedAdmin($admin, 'index');
            self::AssertReady();
            $page = self::PositivePage($params['page'] ?? 1, 1);
            $page_size = min(self::PositivePage($params['page_size'] ?? 20, 20), 100);
            $start = ($page-1)*$page_size;
            $query = Db::name('PluginsNurseryInquiry')->alias('i')
                ->leftJoin('user u', 'u.id=i.user_id');
            self::ApplyAdminFilters($query, $params);
            $total = intval($query->count());

            $query = Db::name('PluginsNurseryInquiry')->alias('i')
                ->leftJoin('user u', 'u.id=i.user_id');
            self::ApplyAdminFilters($query, $params);
            $items = $query
                ->field("i.id,i.inquiry_no,i.user_id,i.goods_id,i.goods_title,i.goods_images,i.quantity,i.quantity_unit,i.contact_phone,i.region_province_name,i.region_city_name,i.region_county_name,i.status,i.first_replied_at,i.created_at,i.updated_at,u.username AS user_username,u.nickname AS user_nickname,CASE WHEN i.first_replied_at IS NULL AND i.created_at <= DATE_SUB(NOW(), INTERVAL 24 HOUR) THEN 1 ELSE 0 END AS is_overdue")
                ->order('i.id desc')
                ->limit($start, $page_size)
                ->select()
                ->toArray();
            foreach($items as &$item)
            {
                self::DecorateInquiryRow($item, true);
            }
            unset($item);
            return DataReturn('询价管理列表读取成功', 0, self::PageData($items, $total, $page, $page_size));
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            return DataReturn('询价管理列表暂时无法读取，请稍后重试', -1);
        }
    }

    public static function AdminDetail($admin, $params = [])
    {
        try {
            self::AuthenticatedAdmin($admin, 'detail');
            self::AssertReady();
            $inquiry_id = self::StrictInquiryId($params['inquiry_id'] ?? ($params['id'] ?? null));
            $inquiry = Db::name('PluginsNurseryInquiry')->alias('i')
                ->leftJoin('user u', 'u.id=i.user_id')
                ->where(['i.id'=>$inquiry_id])
                ->field('i.*,u.username AS user_username,u.nickname AS user_nickname')
                ->find();
            if(empty($inquiry))
            {
                throw new InquiryPublicException('询价记录不存在');
            }
            return self::DetailResponse($inquiry, false);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            return DataReturn('询价详情暂时无法读取，请稍后重试', -1);
        }
    }

    public static function AdminReply($admin, $params = [])
    {
        $connection = null;
        $transaction_started = false;
        try {
            $actor = self::AuthenticatedAdmin($admin, 'reply');
            self::AssertReady();
            $inquiry_id = self::StrictInquiryId($params['inquiry_id'] ?? ($params['id'] ?? null));
            $reply = self::ValidateReply($params);
            $connection = Db::connect();
            $connection->startTrans();
            $transaction_started = true;
            $inquiry = self::LockedInquiry($inquiry_id, $connection);
            $from_status = (string) $inquiry['status'];
            $to_status = InquiryStateMachine::ReplyTarget($from_status);
            $clock = self::DatabaseClock($connection);
            $reply_id = self::Table($connection, 'PluginsNurseryInquiryReply')->insertGetId(array_merge($reply, [
                'inquiry_id' => $inquiry_id,
                'admin_id'   => $actor['id'],
                'admin_name' => $actor['name'],
                'created_at' => $clock['datetime'],
            ]));
            if(intval($reply_id) <= 0)
            {
                throw new \RuntimeException('询价回复写入失败');
            }
            $update = ['status'=>$to_status, 'updated_at'=>$clock['datetime']];
            if(empty($inquiry['first_replied_at']))
            {
                $update['first_replied_at'] = $clock['datetime'];
            }
            $updated = self::Table($connection, 'PluginsNurseryInquiry')->where(['id'=>$inquiry_id, 'status'=>$from_status])->update($update);
            if($updated !== 1 && !($updated === 0 && $from_status === $to_status && !empty($inquiry['first_replied_at'])))
            {
                throw new \RuntimeException('询价回复状态并发更新失败');
            }
            self::AppendHistory([
                'inquiry_id' => $inquiry_id,
                'from_status'=> $from_status,
                'to_status'  => $to_status,
                'actor_type' => 'admin',
                'actor_id'   => $actor['id'],
                'actor_name' => $actor['name'],
                'event_type' => 'reply_added',
                'reason'     => '管理员追加询价回复',
                'reply_id'   => intval($reply_id),
                'created_at' => $clock['datetime'],
            ], $connection);
            $connection->commit();
            $transaction_started = false;
            return DataReturn('询价回复成功', 0, [
                'inquiry_id' => $inquiry_id,
                'reply_id'   => intval($reply_id),
                'status'     => $to_status,
                'status_text'=> InquiryStateMachine::Label($to_status),
            ]);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn('询价回复失败，请稍后重试', -1);
        }
    }

    public static function AdminStatusUpdate($admin, $params = [])
    {
        return self::AdminTransition($admin, $params, false);
    }

    public static function AdminReopen($admin, $params = [])
    {
        return self::AdminTransition($admin, $params, true);
    }

    public static function AdminContactReveal($admin, $params = [])
    {
        $connection = null;
        $transaction_started = false;
        try {
            $actor = self::AuthenticatedAdmin($admin, 'contactreveal');
            self::AssertReady();
            $inquiry_id = self::StrictInquiryId($params['inquiry_id'] ?? ($params['id'] ?? null));
            $connection = Db::connect();
            $connection->startTrans();
            $transaction_started = true;
            $inquiry = self::LockedInquiry($inquiry_id, $connection);
            $clock = self::DatabaseClock($connection);
            self::AppendHistory([
                'inquiry_id' => $inquiry_id,
                'from_status'=> (string) $inquiry['status'],
                'to_status'  => (string) $inquiry['status'],
                'actor_type' => 'admin',
                'actor_id'   => $actor['id'],
                'actor_name' => $actor['name'],
                'event_type' => 'contact_reveal',
                'reason'     => '管理员查看完整联系电话',
                'reply_id'   => null,
                'created_at' => $clock['datetime'],
            ], $connection);
            $connection->commit();
            $transaction_started = false;

            // Decrypt only after the append-only audit transaction is durable.
            $phone = self::DecryptPhone((string) $inquiry['contact_phone']);
            return DataReturn('联系电话读取成功', 0, [
                'inquiry_id'   => $inquiry_id,
                'contact_phone'=> $phone,
            ]);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn('联系电话暂时无法读取，请稍后重试', -1);
        }
    }

    public static function WebRequestNonce($scope = 'user')
    {
        $key = ($scope === 'admin') ? self::ADMIN_NONCE_SESSION_KEY : self::USER_NONCE_SESSION_KEY;
        $nonce = MySession($key);
        if(!is_string($nonce) || preg_match('/^[a-f0-9]{64}$/D', $nonce) !== 1)
        {
            $nonce = bin2hex(random_bytes(32));
            MySession($key, $nonce);
        }
        return $nonce;
    }

    public static function ValidateWebWrite($params = [], $scope = 'user')
    {
        if(!request()->isPost() || !IS_AJAX)
        {
            return DataReturn('询价写操作仅接受站内异步 POST 请求', -1);
        }
        $key = ($scope === 'admin') ? self::ADMIN_NONCE_SESSION_KEY : self::USER_NONCE_SESSION_KEY;
        $provided = isset($params['request_nonce']) && is_string($params['request_nonce']) ? $params['request_nonce'] : '';
        $expected = MySession($key);
        if(!is_string($expected) || strlen($expected) !== 64 || strlen($provided) !== 64 || !hash_equals($expected, $provided))
        {
            return DataReturn('询价请求校验失败，请刷新页面后重试', -1);
        }
        return DataReturn('success', 0);
    }

    private static function AdminTransition($admin, $params, $is_reopen)
    {
        $connection = null;
        $transaction_started = false;
        try {
            $action = $is_reopen ? 'reopen' : 'statusupdate';
            $actor = self::AuthenticatedAdmin($admin, $action);
            self::AssertReady();
            $inquiry_id = self::StrictInquiryId($params['inquiry_id'] ?? ($params['id'] ?? null));
            $reason = self::NormalizeText($params['reason'] ?? '', '处理原因', 500, $is_reopen, true);
            $connection = Db::connect();
            $connection->startTrans();
            $transaction_started = true;
            $inquiry = self::LockedInquiry($inquiry_id, $connection);
            $from_status = (string) $inquiry['status'];
            self::AssertAuditReasonSafe($reason, (string) $inquiry['contact_phone']);
            if($is_reopen)
            {
                $to_status = InquiryStateMachine::AssertReopen($from_status, $reason);
                $event_type = 'reopened';
                $history_reason = $reason;
            } else {
                $to_status = self::StrictStatus($params['status'] ?? ($params['target_status'] ?? null));
                InquiryStateMachine::AssertAdminTransition($from_status, $to_status);
                $event_type = 'status_changed';
                $history_reason = ($reason === '') ? '管理员更新询价状态' : $reason;
            }
            $clock = self::DatabaseClock($connection);
            $updated = self::Table($connection, 'PluginsNurseryInquiry')
                ->where(['id'=>$inquiry_id, 'status'=>$from_status])
                ->update(['status'=>$to_status, 'updated_at'=>$clock['datetime']]);
            if($updated !== 1)
            {
                throw new \RuntimeException('询价状态并发更新失败');
            }
            self::AppendHistory([
                'inquiry_id' => $inquiry_id,
                'from_status'=> $from_status,
                'to_status'  => $to_status,
                'actor_type' => 'admin',
                'actor_id'   => $actor['id'],
                'actor_name' => $actor['name'],
                'event_type' => $event_type,
                'reason'     => $history_reason,
                'reply_id'   => null,
                'created_at' => $clock['datetime'],
            ], $connection);
            $connection->commit();
            $transaction_started = false;
            return DataReturn($is_reopen ? '询价已重开' : '询价状态更新成功', 0, [
                'inquiry_id' => $inquiry_id,
                'status'     => $to_status,
                'status_text'=> InquiryStateMachine::Label($to_status),
            ]);
        } catch(InquiryPublicException|\InvalidArgumentException|\DomainException $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn($e->getMessage(), -1);
        } catch(\Throwable $e) {
            if($transaction_started)
            {
                self::SafeRollback($connection);
            }
            return DataReturn($is_reopen ? '询价重开失败，请稍后重试' : '询价状态更新失败，请稍后重试', -1);
        }
    }

    private static function DetailResponse($inquiry, $is_owner)
    {
        $inquiry_id = intval($inquiry['id']);
        // Full contact data is never part of a normal detail response.  The
        // dedicated contact-reveal action is the sole audited plaintext path.
        self::DecorateInquiryRow($inquiry, true);
        $replies = Db::name('PluginsNurseryInquiryReply')
            ->where(['inquiry_id'=>$inquiry_id])
            ->field('id,inquiry_id,admin_name,stock_note,available_spec,unit_price,total_amount,transport_fee,loading_fee,planting_fee,other_fee,supply_date,valid_until,reply_note,created_at')
            ->order('id asc')
            ->select()
            ->toArray();
        $history = Db::name('PluginsNurseryInquiryHistory')
            ->where(['inquiry_id'=>$inquiry_id])
            ->field('id,inquiry_id,from_status,to_status,actor_type,actor_id,actor_name,event_type,reason,reply_id,created_at')
            ->order('id asc')
            ->select()
            ->toArray();
        foreach($history as &$item)
        {
            $item['from_status_text'] = InquiryStateMachine::Label((string) $item['from_status']);
            $item['to_status_text'] = InquiryStateMachine::Label((string) $item['to_status']);
            $item['event_text'] = self::HistoryEventText((string) $item['event_type'], (string) $item['to_status']);
            $item['created_at_text'] = empty($item['created_at']) ? '' : date('Y-m-d H:i', strtotime((string) $item['created_at']));
            if($is_owner && (string) $item['actor_type'] === 'admin')
            {
                $item['actor_id'] = 0;
                $item['actor_name'] = '苗木顾问';
            }
        }
        unset($item);
        foreach($replies as &$reply)
        {
            $reply['created_at_text'] = empty($reply['created_at']) ? '' : date('Y-m-d H:i', strtotime((string) $reply['created_at']));
            if($is_owner)
            {
                $reply['admin_name'] = '苗木顾问';
            }
        }
        unset($reply);
        $goods = Db::name('Goods')->where(['id'=>intval($inquiry['goods_id']), 'is_shelves'=>1, 'is_delete_time'=>0])->field('id')->find();
        $inquiry['can_view_goods'] = !empty($goods);
        $inquiry['goods_url'] = empty($goods) ? '' : MyUrl('index/goods/index', ['id'=>intval($inquiry['goods_id'])]);
        return DataReturn('询价详情读取成功', 0, [
            'inquiry'       => $inquiry,
            'replies'       => $replies,
            'history'       => $history,
            'status_options'=> InquiryStateMachine::Labels(),
        ]);
    }

    private static function HistoryEventText($event_type, $to_status)
    {
        $events = [
            'created'        => '询价已提交',
            'reply_added'    => '管理员追加回复',
            'user_viewed'    => '用户已查看回复',
            'status_changed' => '管理员更新状态',
            'reopened'       => '管理员重开询价',
            'contact_reveal' => '管理员查看联系电话',
        ];
        return $events[$event_type] ?? InquiryStateMachine::Label($to_status);
    }

    private static function DecorateInquiryRow(&$row, $mask_phone)
    {
        $row['id'] = intval($row['id']);
        $row['user_id'] = isset($row['user_id']) ? intval($row['user_id']) : null;
        $row['goods_id'] = intval($row['goods_id']);
        $row['spec_base_id'] = empty($row['spec_base_id']) ? null : intval($row['spec_base_id']);
        $row['spec_snapshot'] = self::DecodeJsonObject($row['spec_snapshot'] ?? '');
        $row['spec_snapshot_text'] = '';
        if(!empty($row['spec_snapshot']['text']))
        {
            $row['spec_snapshot_text'] = (string) $row['spec_snapshot']['text'];
        } elseif(!empty($row['spec_snapshot']['items']) && is_array($row['spec_snapshot']['items'])) {
            $parts = [];
            foreach($row['spec_snapshot']['items'] as $item)
            {
                if(is_array($item) && isset($item['type'], $item['value']))
                {
                    $parts[] = $item['type'].'：'.$item['value'];
                }
            }
            $row['spec_snapshot_text'] = implode(' / ', $parts);
        }
        $region_parts = [];
        foreach(['region_province_name', 'region_city_name', 'region_county_name'] as $region_field)
        {
            if(isset($row[$region_field]) && trim((string) $row[$region_field]) !== '')
            {
                $region_parts[] = (string) $row[$region_field];
            }
        }
        $row['region_text'] = implode(' / ', $region_parts);
        $service_parts = [];
        foreach(['need_transport'=>'运输', 'need_loading'=>'装卸', 'need_planting'=>'栽植'] as $flag=>$label)
        {
            if(!empty($row[$flag]))
            {
                $service_parts[] = $label;
            }
        }
        $row['service_text'] = empty($service_parts) ? '无特别服务需求' : implode('、', $service_parts);
        $row['created_at_text'] = empty($row['created_at']) ? '' : date('Y-m-d H:i', strtotime((string) $row['created_at']));
        $row['user_name'] = trim((string) ($row['user_nickname'] ?? ''));
        if($row['user_name'] === '')
        {
            $row['user_name'] = trim((string) ($row['user_username'] ?? ''));
        }
        if($row['user_name'] === '' && !empty($row['user_id']))
        {
            $row['user_name'] = '用户#'.intval($row['user_id']);
        }
        if(array_key_exists('contact_phone', $row))
        {
            $decrypted_phone = self::DecryptPhone((string) $row['contact_phone']);
            $row['contact_phone_masked'] = self::MaskPhone($decrypted_phone);
            if(!$mask_phone)
            {
                $row['contact_phone'] = $decrypted_phone;
            }
        }
        $row['status_text'] = InquiryStateMachine::Label((string) $row['status']);
        if($mask_phone)
        {
            unset($row['contact_phone']);
        }
        unset($row['contact_phone_hash']);
    }

    private static function ApplyAdminFilters($query, $params)
    {
        if(isset($params['inquiry_no']) && trim((string) $params['inquiry_no']) !== '')
        {
            $value = self::NormalizeText((string) $params['inquiry_no'], '询价编号', 32, true, false);
            if(preg_match('/^[a-f0-9]{32}$/D', $value) !== 1)
            {
                throw new InquiryPublicException('询价编号格式无效');
            }
            $query->where(['i.inquiry_no'=>$value]);
        }
        if(isset($params['goods']) && trim((string) $params['goods']) !== '')
        {
            $value = self::NormalizeText((string) $params['goods'], '商品筛选', 160, true, false);
            if(preg_match('/^[1-9][0-9]*$/D', $value) === 1)
            {
                $query->where(['i.goods_id'=>intval($value)]);
            } else {
                $query->whereLike('i.goods_title', '%'.self::EscapeLike($value).'%');
            }
        }
        if(isset($params['user_id']) && $params['user_id'] !== '')
        {
            $query->where(['i.user_id'=>self::StrictUnsignedId($params['user_id'], '用户编号')]);
        }
        if(isset($params['user_keyword']) && trim((string) $params['user_keyword']) !== '')
        {
            $value = self::NormalizeText((string) $params['user_keyword'], '用户筛选', 80, true, false);
            $query->where(function($nested) use ($value) {
                $escaped = self::EscapeLike($value);
                $nested->whereLike('u.username', '%'.$escaped.'%')->whereLike('u.nickname', '%'.$escaped.'%', 'OR');
            });
        }
        if(isset($params['mobile']) && trim((string) $params['mobile']) !== '')
        {
            $phone = self::NormalizePhone($params['mobile']);
            $query->where(['i.contact_phone_hash'=>self::PhoneHash($phone)]);
        }
        if(isset($params['status']) && $params['status'] !== '')
        {
            $query->where(['i.status'=>self::StrictStatus($params['status'])]);
        }
        foreach(['region_province_id', 'region_city_id', 'region_county_id'] as $field)
        {
            if(isset($params[$field]) && $params[$field] !== '')
            {
                $query->where(['i.'.$field=>self::StrictUnsignedId($params[$field], '地区编号')]);
            }
        }
        if(isset($params['created_start']) && $params['created_start'] !== '')
        {
            $query->where('i.created_at', '>=', self::NormalizeDate($params['created_start'], '开始日期', false).' 00:00:00');
        }
        if(isset($params['created_end']) && $params['created_end'] !== '')
        {
            $query->where('i.created_at', '<=', self::NormalizeDate($params['created_end'], '结束日期', false).' 23:59:59');
        }
        if(isset($params['is_overdue']) && in_array((string) $params['is_overdue'], ['0', '1'], true))
        {
            if((string) $params['is_overdue'] === '1')
            {
                $query->whereRaw('i.first_replied_at IS NULL AND i.created_at <= DATE_SUB(NOW(), INTERVAL 24 HOUR)');
            } else {
                $query->whereRaw('(i.first_replied_at IS NOT NULL OR i.created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR))');
            }
        }
    }

    private static function ValidateSubmission($user_id, $params)
    {
        if(!is_array($params))
        {
            throw new InquiryPublicException('询价参数格式无效');
        }
        $goods_id = self::StrictUnsignedId($params['goods_id'] ?? null, '商品编号');
        $snapshot = self::PublishedGoodsSnapshot($goods_id, $params['spec_base_id'] ?? null, true);
        $quantity = self::NormalizeQuantity($params['quantity'] ?? null);
        $quantity_unit = isset($params['quantity_unit']) && $params['quantity_unit'] !== ''
            ? self::NormalizeText($params['quantity_unit'], '采购单位', 32, true, false)
            : $snapshot['reference_unit'];
        if(!hash_equals($snapshot['reference_unit'], $quantity_unit))
        {
            throw new InquiryPublicException('采购单位必须与商品公开计量单位一致');
        }
        $contact_name = self::NormalizeText($params['contact_name'] ?? null, '联系人', 80, true, false);
        $contact_phone = self::NormalizePhone($params['contact_phone'] ?? null);
        $province_id = self::StrictUnsignedId($params['region_province_id'] ?? ($params['province_id'] ?? null), '省份编号');
        $city_id = self::StrictUnsignedId($params['region_city_id'] ?? ($params['city_id'] ?? null), '城市编号');
        $county_id = self::StrictUnsignedId($params['region_county_id'] ?? ($params['county_id'] ?? null), '区县编号');
        $region = self::ValidatedRegion($province_id, $city_id, $county_id);
        $address = self::NormalizeText($params['address'] ?? null, '详细地址', 255, true, true);
        $expected_date = self::NormalizeDate($params['expected_date'] ?? null, '预计采购日期', false);
        $need_transport = self::NormalizeBoolean($params['need_transport'] ?? 0, '运输需求');
        $need_loading = self::NormalizeBoolean($params['need_loading'] ?? 0, '装卸需求');
        $need_planting = self::NormalizeBoolean($params['need_planting'] ?? 0, '栽植需求');
        $user_note = self::NormalizeText($params['user_note'] ?? '', '用户说明', 2000, false, true);

        // Secret and crypto checks occur only after all business input is valid.
        $instance_key = self::InstanceSecret();
        $canonical = [
            'address'            => ['type'=>'string', 'value'=>$address],
            'contact_name'       => ['type'=>'string', 'value'=>$contact_name],
            'contact_phone'      => ['type'=>'phone', 'value'=>$contact_phone],
            'expected_date'      => ['type'=>'date', 'value'=>$expected_date],
            'goods_id'           => ['type'=>'integer', 'value'=>$goods_id],
            'need_loading'       => ['type'=>'boolean', 'value'=>(bool) $need_loading],
            'need_planting'      => ['type'=>'boolean', 'value'=>(bool) $need_planting],
            'need_transport'     => ['type'=>'boolean', 'value'=>(bool) $need_transport],
            'quantity'           => ['type'=>'decimal', 'value'=>$quantity],
            'quantity_unit'      => ['type'=>'string', 'value'=>$quantity_unit],
            'reference_price'    => ['type'=>'object', 'value'=>[
                'display'=>$snapshot['reference_price'],
                'min'=>$snapshot['reference_min'],
                'max'=>$snapshot['reference_max'],
                'unit'=>$snapshot['reference_unit'],
            ]],
            'region'             => ['type'=>'integer_tuple', 'value'=>[$province_id, $city_id, $county_id]],
            'specification'      => ['type'=>'ordered_specification', 'value'=>[
                'items'=>$snapshot['selected_spec']['items'],
                'price'=>$snapshot['selected_spec']['price'],
                'unit'=>$snapshot['selected_spec']['unit'],
            ]],
            'user_id'            => ['type'=>'integer', 'value'=>$user_id],
            'user_note'          => ['type'=>'string', 'value'=>$user_note],
        ];
        ksort($canonical, SORT_STRING);
        $canonical_json = json_encode($canonical, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_PRESERVE_ZERO_FRACTION|JSON_THROW_ON_ERROR);
        $fingerprint = hash_hmac('sha256', $canonical_json, $instance_key, false);

        return [
            'fingerprint_version' => self::FINGERPRINT_VERSION,
            'fingerprint_digest'  => $fingerprint,
            'inquiry' => [
                'user_id'              => $user_id,
                'goods_id'             => $goods_id,
                'goods_title'          => $snapshot['goods_title'],
                'goods_images'         => $snapshot['goods_images'],
                'goods_status'         => $snapshot['goods_status'],
                'reference_price'      => $snapshot['reference_price'],
                'reference_min'        => $snapshot['reference_min'],
                'reference_max'        => $snapshot['reference_max'],
                'reference_unit'       => $snapshot['reference_unit'],
                'spec_base_id'         => $snapshot['selected_spec']['base_id'],
                'spec_snapshot'        => json_encode($snapshot['selected_spec'], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR),
                'quantity'             => $quantity,
                'quantity_unit'        => $quantity_unit,
                'contact_name'         => $contact_name,
                'contact_phone'        => self::EncryptPhone($contact_phone, $instance_key),
                'contact_phone_hash'   => self::PhoneHash($contact_phone, $instance_key),
                'region_province_id'   => $province_id,
                'region_city_id'       => $city_id,
                'region_county_id'     => $county_id,
                'region_province_name' => $region['province']['name'],
                'region_city_name'     => $region['city']['name'],
                'region_county_name'   => $region['county']['name'],
                'region_province_code' => $region['province']['code'],
                'region_city_code'     => $region['city']['code'],
                'region_county_code'   => $region['county']['code'],
                'address'               => $address,
                'expected_date'         => $expected_date,
                'need_transport'        => $need_transport,
                'need_loading'          => $need_loading,
                'need_planting'         => $need_planting,
                'user_note'             => $user_note,
            ],
        ];
    }

    private static function PublishedGoodsSnapshot($goods_id, $requested_spec_base_id, $select_one)
    {
        $goods = Db::name('Goods')->where(['id'=>$goods_id])->field('id,title,images,price,min_price,max_price,inventory_unit,is_shelves,is_delete_time')->find();
        if(empty($goods) || intval($goods['is_shelves']) !== 1 || intval($goods['is_delete_time']) !== 0)
        {
            throw new InquiryPublicException('该商品当前不可提交询价');
        }
        try {
            ReferencePriceService::AssertPublishedGoods($goods_id);
        } catch(\Throwable $e) {
            throw new InquiryPublicException('该商品公开参考价暂不可用于询价');
        }
        $reference_unit = self::NormalizeText((string) $goods['inventory_unit'], '商品计量单位', 32, true, false);
        $reference_min = self::ValidStoredPrice($goods['min_price'], '商品最低参考价');
        $reference_max = self::ValidStoredPrice($goods['max_price'], '商品最高参考价');
        if(ReferencePriceService::StoredPriceToCents($reference_max) < ReferencePriceService::StoredPriceToCents($reference_min))
        {
            throw new InquiryPublicException('商品公开参考价区间无效');
        }
        $bases = Db::name('GoodsSpecBase')->where(['goods_id'=>$goods_id])->field('id,goods_id,price,inventory,inventory_unit')->order('id asc')->select()->toArray();
        if(empty($bases))
        {
            throw new InquiryPublicException('该商品缺少可询价规格');
        }
        $types = self::GoodsSpecTypes($goods_id);
        $options = [];
        foreach($bases as $base)
        {
            $options[] = self::BuildSpecOption($goods_id, $base, $types, $reference_unit);
        }
        $selected = null;
        if($requested_spec_base_id !== null && $requested_spec_base_id !== '')
        {
            $base_id = self::StrictUnsignedId($requested_spec_base_id, '规格编号');
            foreach($options as $option)
            {
                if($option['base_id'] === $base_id)
                {
                    $selected = $option;
                    break;
                }
            }
            if($selected === null)
            {
                throw new InquiryPublicException('所选规格不属于当前商品');
            }
        } elseif(count($options) === 1) {
            $selected = $options[0];
        } elseif($select_one) {
            throw new InquiryPublicException('请选择有效的商品规格');
        }
        return [
            'goods_id'        => $goods_id,
            'goods_title'     => self::NormalizeSnapshotText((string) $goods['title'], 255),
            'goods_images'    => self::NormalizeSnapshotText((string) $goods['images'], 1024),
            'goods_status'    => 1,
            'reference_price' => self::NormalizeSnapshotText((string) $goods['price'], 60),
            'reference_min'   => $reference_min,
            'reference_max'   => $reference_max,
            'reference_unit'  => $reference_unit,
            'selected_spec'   => $selected,
            'spec_options'    => $options,
        ];
    }

    private static function GoodsSpecTypes($goods_id)
    {
        $rows = Db::name('GoodsSpecType')->where(['goods_id'=>$goods_id])->field('id,name,value')->order('id asc')->select()->toArray();
        $types = [];
        $type_names = [];
        foreach($rows as $row)
        {
            $name = self::NormalizeSnapshotText((string) $row['name'], 180);
            $decoded = json_decode((string) $row['value'], true);
            if(!is_array($decoded) || $name === '' || isset($type_names[$name]))
            {
                throw new InquiryPublicException('商品规格定义无效');
            }
            $type_names[$name] = true;
            $allowed = [];
            foreach($decoded as $item)
            {
                if(!is_array($item) || !isset($item['name']))
                {
                    throw new InquiryPublicException('商品规格值定义无效');
                }
                $value = self::NormalizeSnapshotText((string) $item['name'], 230);
                if($value === '' || in_array($value, $allowed, true))
                {
                    throw new InquiryPublicException('商品规格值定义存在冲突');
                }
                $allowed[] = $value;
            }
            $types[] = ['id'=>intval($row['id']), 'type'=>$name, 'allowed'=>$allowed];
        }
        return $types;
    }

    private static function BuildSpecOption($goods_id, $base, $types, $reference_unit)
    {
        $base_id = intval($base['id']);
        if($base_id <= 0 || intval($base['goods_id']) !== $goods_id)
        {
            throw new InquiryPublicException('商品规格归属无效');
        }
        $price = self::ValidStoredPrice($base['price'], '规格公开参考价');
        if(ReferencePriceService::StoredPriceToCents($price) < 1)
        {
            throw new InquiryPublicException('规格公开参考价无效');
        }
        $base_unit = trim((string) ($base['inventory_unit'] ?? ''));
        $unit = ($base_unit === '') ? $reference_unit : self::NormalizeSnapshotText($base_unit, 32);
        if(!hash_equals($reference_unit, $unit))
        {
            throw new InquiryPublicException('规格计量单位与商品公开单位不一致');
        }
        $values = Db::name('GoodsSpecValue')->where(['goods_id'=>$goods_id, 'goods_spec_base_id'=>$base_id])->field('value')->order('id asc')->column('value');
        $normalized_values = [];
        foreach($values as $value)
        {
            $normalized_values[] = self::NormalizeSnapshotText((string) $value, 230);
        }
        if(count($normalized_values) !== count($types))
        {
            throw new InquiryPublicException('商品规格值数量与规格类型不一致');
        }
        $items = [];
        $used = [];
        foreach($types as $type)
        {
            $matches = [];
            foreach($normalized_values as $index=>$value)
            {
                if(!isset($used[$index]) && in_array($value, $type['allowed'], true))
                {
                    $matches[] = $index;
                }
            }
            if(count($matches) !== 1)
            {
                throw new InquiryPublicException('商品规格类型和值无法唯一对应');
            }
            $index = $matches[0];
            $used[$index] = true;
            $items[] = ['type'=>$type['type'], 'value'=>$normalized_values[$index]];
        }
        if(count($used) !== count($normalized_values))
        {
            throw new InquiryPublicException('商品规格包含未识别的值');
        }
        usort($items, function($left, $right) {
            $type_order = strcmp($left['type'], $right['type']);
            return ($type_order === 0) ? strcmp($left['value'], $right['value']) : $type_order;
        });
        return [
            'version'   => 'spec-snapshot-v1',
            'base_id'   => $base_id,
            'id'        => $base_id,
            'items'     => $items,
            'price'     => $price,
            'unit'      => $unit,
            'inventory' => intval($base['inventory']),
            'text'      => implode(' / ', array_map(function($item) {
                return $item['type'].'：'.$item['value'];
            }, $items)),
            'label'     => implode(' / ', array_map(function($item) {
                return $item['type'].'：'.$item['value'];
            }, $items)),
        ];
    }

    private static function ConsumeRateLimit($user_id)
    {
        for($attempt = 0; $attempt < 2; $attempt++)
        {
            $connection = Db::connect();
            $started = false;
            try {
                $connection->startTrans();
                $started = true;
                $clock = self::DatabaseClock($connection);
                $row = self::Table($connection, 'PluginsNurseryInquiryRateLimit')
                    ->where(['user_id'=>$user_id])
                    ->field('user_id,window_started_at,UNIX_TIMESTAMP(window_started_at) AS window_started_unix,attempt_count')
                    ->lock(true)
                    ->find();
                if(empty($row))
                {
                    $inserted = self::Table($connection, 'PluginsNurseryInquiryRateLimit')->insert([
                        'user_id'           => $user_id,
                        'window_started_at' => $clock['datetime'],
                        'attempt_count'     => 1,
                        'updated_at'        => $clock['datetime'],
                    ]);
                    if($inserted !== 1)
                    {
                        throw new \RuntimeException('询价频率限制初始化失败');
                    }
                } else {
                    $started_at = isset($row['window_started_unix']) ? intval($row['window_started_unix']) : 0;
                    if($started_at <= 0 || $clock['unix'] < $started_at)
                    {
                        throw new InquiryPublicException('询价频率时间状态异常，请稍后重试');
                    }
                    $elapsed = $clock['unix']-$started_at;
                    if($elapsed >= self::RATE_WINDOW_SECONDS)
                    {
                        $update = [
                            'window_started_at' => $clock['datetime'],
                            'attempt_count'     => 1,
                            'updated_at'        => $clock['datetime'],
                        ];
                    } else {
                        $count = intval($row['attempt_count']);
                        if($count >= self::RATE_MAX_ATTEMPTS)
                        {
                            throw new InquiryPublicException('询价提交过于频繁，请稍后再试');
                        }
                        $update = [
                            'attempt_count' => $count+1,
                            'updated_at'    => $clock['datetime'],
                        ];
                    }
                    $updated = self::Table($connection, 'PluginsNurseryInquiryRateLimit')->where(['user_id'=>$user_id])->update($update);
                    if($updated !== 1)
                    {
                        throw new \RuntimeException('询价频率限制更新失败');
                    }
                }
                $connection->commit();
                return;
            } catch(\Throwable $e) {
                if($started)
                {
                    self::SafeRollback($connection);
                }
                if($attempt === 0 && self::IsDuplicateKeyError($e))
                {
                    continue;
                }
                throw $e;
            }
        }
        throw new InquiryPublicException('询价提交冲突，请稍后重试');
    }

    private static function CreateInquiry($user_id, $validated)
    {
        $connection = Db::connect();
        $started = false;
        try {
            $connection->startTrans();
            $started = true;
            $clock = self::DatabaseClock($connection);
            $guard_where = [
                'user_id'            => $user_id,
                'goods_id'           => intval($validated['inquiry']['goods_id']),
                'fingerprint_version'=> $validated['fingerprint_version'],
                'fingerprint_digest' => $validated['fingerprint_digest'],
            ];
            $guard = self::Table($connection, 'PluginsNurseryInquiryDuplicateGuard')
                ->where($guard_where)
                ->field('id,last_accepted_at,UNIX_TIMESTAMP(last_accepted_at) AS last_accepted_unix,inquiry_id')
                ->lock(true)
                ->find();
            if(!empty($guard))
            {
                $last = isset($guard['last_accepted_unix']) ? intval($guard['last_accepted_unix']) : 0;
                if($last <= 0 || $clock['unix'] < $last)
                {
                    throw new InquiryPublicException('重复询价时间状态异常，请稍后重试');
                }
                if($clock['unix']-$last < self::DUPLICATE_WINDOW_SECONDS)
                {
                    throw new InquiryPublicException('相同询价已提交，请勿重复操作');
                }
            }

            $inquiry_no = bin2hex(random_bytes(16));
            $inquiry_data = array_merge($validated['inquiry'], [
                'inquiry_no'      => $inquiry_no,
                'status'          => InquiryStateMachine::PENDING,
                'first_replied_at'=> null,
                'created_at'      => $clock['datetime'],
                'updated_at'      => $clock['datetime'],
            ]);
            $inquiry_id = self::Table($connection, 'PluginsNurseryInquiry')->insertGetId($inquiry_data);
            if(intval($inquiry_id) <= 0)
            {
                throw new \RuntimeException('询价主记录写入失败');
            }
            self::AppendHistory([
                'inquiry_id' => intval($inquiry_id),
                'from_status'=> '',
                'to_status'  => InquiryStateMachine::PENDING,
                'actor_type' => 'user',
                'actor_id'   => $user_id,
                'actor_name' => '用户#'.$user_id,
                'event_type' => 'created',
                'reason'     => '用户提交询价',
                'reply_id'   => null,
                'created_at' => $clock['datetime'],
            ], $connection);
            if(empty($guard))
            {
                $inserted = self::Table($connection, 'PluginsNurseryInquiryDuplicateGuard')->insert(array_merge($guard_where, [
                    'last_accepted_at' => $clock['datetime'],
                    'inquiry_id'       => intval($inquiry_id),
                ]));
                if($inserted !== 1)
                {
                    throw new \RuntimeException('询价防重复守卫写入失败');
                }
            } else {
                $updated = self::Table($connection, 'PluginsNurseryInquiryDuplicateGuard')
                    ->where(['id'=>intval($guard['id']), 'inquiry_id'=>intval($guard['inquiry_id']), 'last_accepted_at'=>$guard['last_accepted_at']])
                    ->update(['last_accepted_at'=>$clock['datetime'], 'inquiry_id'=>intval($inquiry_id)]);
                if($updated !== 1)
                {
                    throw new \RuntimeException('询价防重复守卫并发更新失败');
                }
            }
            $connection->commit();
            $started = false;
            return [
                'id'          => intval($inquiry_id),
                'inquiry_id'  => intval($inquiry_id),
                'inquiry_no'  => $inquiry_no,
                'status'      => InquiryStateMachine::PENDING,
                'status_text' => InquiryStateMachine::Label(InquiryStateMachine::PENDING),
            ];
        } catch(\Throwable $e) {
            if($started)
            {
                self::SafeRollback($connection);
            }
            if(self::IsDuplicateKeyError($e))
            {
                throw new InquiryPublicException('相同询价已提交，请勿重复操作');
            }
            throw $e;
        }
    }

    private static function ValidateReply($params)
    {
        if(!is_array($params))
        {
            throw new InquiryPublicException('回复参数格式无效');
        }
        return [
            'stock_note'     => self::NormalizeText($params['stock_note'] ?? null, '库存说明', 2000, true, true),
            'available_spec' => self::NormalizeText($params['available_spec'] ?? null, '可供应规格', 2000, true, true),
            'unit_price'     => self::NormalizeMoney($params['unit_price'] ?? null, '本次参考单价', true),
            'total_amount'   => self::NormalizeMoney($params['total_amount'] ?? null, '总金额', false),
            'transport_fee'  => self::NormalizeMoney($params['transport_fee'] ?? null, '运输费', false),
            'loading_fee'    => self::NormalizeMoney($params['loading_fee'] ?? null, '装卸费', false),
            'planting_fee'   => self::NormalizeMoney($params['planting_fee'] ?? null, '栽植费', false),
            'other_fee'      => self::NormalizeMoney($params['other_fee'] ?? null, '其他费用', false),
            'supply_date'    => self::NormalizeDate($params['supply_date'] ?? null, '供应日期', true),
            'valid_until'    => self::NormalizeDate($params['valid_until'] ?? null, '报价有效期', false),
            'reply_note'     => self::NormalizeText($params['reply_note'] ?? '', '回复说明', 4000, true, true),
        ];
    }

    private static function RegionOptionData($region_rows = null)
    {
        if($region_rows === null)
        {
            $region_rows = Db::name('Region')->where([['is_enable', '=', 1], ['level', 'in', [1, 2, 3]]])
                ->field('id,pid,name,level,code')
                ->order('level asc,sort asc,id asc')
                ->select()
                ->toArray();
        }
        $regions = ['province'=>[], 'city'=>[], 'county'=>[]];
        foreach($region_rows as $region)
        {
            $key = intval($region['level']) === 1 ? 'province' : (intval($region['level']) === 2 ? 'city' : 'county');
            $regions[$key][] = [
                'id'   => intval($region['id']),
                'pid'  => intval($region['pid']),
                'name' => self::NormalizeSnapshotText((string) $region['name'], 80),
                'code' => self::NormalizeSnapshotText((string) $region['code'], 32),
            ];
        }
        return $regions;
    }

    private static function ValidatedRegion($province_id, $city_id, $county_id)
    {
        $rows = Db::name('Region')
            ->where([['id', 'in', [$province_id, $city_id, $county_id]], ['is_enable', '=', 1]])
            ->field('id,pid,name,level,code')
            ->select()
            ->toArray();
        $by_id = [];
        foreach($rows as $row)
        {
            $by_id[intval($row['id'])] = $row;
        }
        if(!isset($by_id[$province_id], $by_id[$city_id], $by_id[$county_id]))
        {
            throw new InquiryPublicException('请选择有效的省市区县');
        }
        $province = $by_id[$province_id];
        $city = $by_id[$city_id];
        $county = $by_id[$county_id];
        if(intval($province['level']) !== 1 || intval($province['pid']) !== 0 || intval($city['level']) !== 2 || intval($city['pid']) !== $province_id || intval($county['level']) !== 3 || intval($county['pid']) !== $city_id)
        {
            throw new InquiryPublicException('省市区县层级关系无效');
        }
        $province['name'] = self::NormalizeSnapshotText((string) $province['name'], 80);
        $city['name'] = self::NormalizeSnapshotText((string) $city['name'], 80);
        $county['name'] = self::NormalizeSnapshotText((string) $county['name'], 80);
        $province['code'] = self::NormalizeSnapshotText((string) $province['code'], 32);
        $city['code'] = self::NormalizeSnapshotText((string) $city['code'], 32);
        $county['code'] = self::NormalizeSnapshotText((string) $county['code'], 32);
        return ['province'=>$province, 'city'=>$city, 'county'=>$county];
    }

    private static function LockedInquiry($inquiry_id, $connection = null)
    {
        $inquiry = self::Table($connection, 'PluginsNurseryInquiry')->where(['id'=>$inquiry_id])->lock(true)->find();
        if(empty($inquiry))
        {
            throw new InquiryPublicException('询价记录不存在');
        }
        if(!InquiryStateMachine::IsValid((string) $inquiry['status']))
        {
            throw new \RuntimeException('询价状态数据无效');
        }
        return $inquiry;
    }

    private static function AppendHistory($data, $connection = null)
    {
        $inserted = self::Table($connection, 'PluginsNurseryInquiryHistory')->insert($data);
        if($inserted !== 1)
        {
            throw new \RuntimeException('询价审计历史写入失败');
        }
    }

    private static function AssertAuditReasonSafe($reason, $encrypted_phone)
    {
        if($reason === '')
        {
            return;
        }
        $phone_digits = preg_replace('/[^0-9]+/', '', self::DecryptPhone($encrypted_phone));
        $reason_digits = preg_replace('/[^0-9]+/', '', $reason);
        if(strlen($phone_digits) >= 6 && strpos($reason_digits, $phone_digits) !== false)
        {
            throw new InquiryPublicException('处理原因不得包含完整联系电话');
        }
    }

    private static function Table($connection, $name)
    {
        return ($connection === null) ? Db::name($name) : $connection->name($name);
    }

    private static function AuthenticatedUserId($user)
    {
        if(!is_array($user) || !isset($user['id']) || intval($user['id']) <= 0)
        {
            throw new InquiryPublicException('请先登录后提交或查看询价');
        }
        $user_id = intval($user['id']);
        $status = UserService::UserStatusCheck($user_id);
        if(!is_array($status) || intval($status['code'] ?? -1) !== 0)
        {
            throw new InquiryPublicException('当前用户状态不可用');
        }
        return $user_id;
    }

    private static function AuthenticatedAdmin($admin, $action)
    {
        if(!is_array($admin) || !isset($admin['id']) || intval($admin['id']) <= 0)
        {
            throw new InquiryPublicException('管理员身份无效');
        }
        if(!AdminIsPower('inquiry', $action, 'nursery'))
        {
            throw new InquiryPublicException('无权执行该询价管理操作');
        }
        $row = Db::name('Admin')->where(['id'=>intval($admin['id']), 'status'=>0])->field('id,username')->find();
        if(empty($row))
        {
            throw new InquiryPublicException('管理员状态不可用');
        }
        return [
            'id'   => intval($row['id']),
            'name' => self::NormalizeSnapshotText((string) $row['username'], 80),
        ];
    }

    private static function AssertReady()
    {
        try {
            InquiryMigration::AssertReady();
        } catch(\Throwable $e) {
            throw new InquiryPublicException('询价服务尚未完成数据结构初始化');
        }
    }

    private static function DatabaseClock($connection)
    {
        $rows = $connection->query("SELECT UNIX_TIMESTAMP() AS database_unix, DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s') AS database_datetime", [], true);
        if(empty($rows) || intval($rows[0]['database_unix'] ?? 0) <= 0 || empty($rows[0]['database_datetime']))
        {
            throw new \RuntimeException('数据库时间读取失败');
        }
        return [
            'unix'     => intval($rows[0]['database_unix']),
            'datetime' => (string) $rows[0]['database_datetime'],
        ];
    }

    private static function InstanceSecret()
    {
        $instance_key = MyEnv(self::HMAC_ENV_KEY, null);
        if(!is_string($instance_key) || strlen($instance_key) < 32 || strlen($instance_key) > 4096)
        {
            throw new InquiryPublicException('询价安全配置缺失，当前无法提交');
        }
        $lower = strtolower(trim($instance_key));
        if($lower === '' || in_array($lower, ['change-me','changeme','secret','your-secret','replace-me','placeholder'], true))
        {
            throw new InquiryPublicException('询价安全配置无效，当前无法提交');
        }
        return $instance_key;
    }

    private static function PhoneHash($phone, $instance_key = null)
    {
        $instance_key = $instance_key ?? self::InstanceSecret();
        return hash_hmac('sha256', 'phone-v1:'.$phone, $instance_key, false);
    }

    private static function EncryptPhone($phone, $instance_key)
    {
        if(!function_exists('openssl_encrypt') || !function_exists('openssl_cipher_iv_length'))
        {
            throw new InquiryPublicException('服务器缺少联系电话加密能力，当前无法提交');
        }
        $key = hash_hkdf('sha256', $instance_key, 32, 'nursery-inquiry-phone-v1');
        $iv = random_bytes(12);
        $tag = '';
        $cipher = openssl_encrypt($phone, 'aes-256-gcm', $key, OPENSSL_RAW_DATA, $iv, $tag, 'nursery-phone-v1', 16);
        if($cipher === false || strlen($tag) !== 16)
        {
            throw new InquiryPublicException('联系电话加密失败，当前无法提交');
        }
        return 'v1.'.self::Base64UrlEncode($iv.$tag.$cipher);
    }

    private static function DecryptPhone($encoded)
    {
        if(!is_string($encoded) || strpos($encoded, 'v1.') !== 0)
        {
            throw new InquiryPublicException('联系电话数据不可用');
        }
        $instance_key = self::InstanceSecret();
        if(!function_exists('openssl_decrypt'))
        {
            throw new InquiryPublicException('服务器缺少联系电话解密能力');
        }
        $raw = self::Base64UrlDecode(substr($encoded, 3));
        if($raw === false || strlen($raw) < 29)
        {
            throw new InquiryPublicException('联系电话数据不可用');
        }
        $iv = substr($raw, 0, 12);
        $tag = substr($raw, 12, 16);
        $cipher = substr($raw, 28);
        $key = hash_hkdf('sha256', $instance_key, 32, 'nursery-inquiry-phone-v1');
        $phone = openssl_decrypt($cipher, 'aes-256-gcm', $key, OPENSSL_RAW_DATA, $iv, $tag, 'nursery-phone-v1');
        if(!is_string($phone) || preg_match('/^\+?[0-9]{6,20}$/D', $phone) !== 1)
        {
            throw new InquiryPublicException('联系电话数据校验失败');
        }
        return $phone;
    }

    private static function Base64UrlEncode($value)
    {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }

    private static function Base64UrlDecode($value)
    {
        if(!is_string($value) || preg_match('/^[A-Za-z0-9_-]+$/D', $value) !== 1)
        {
            return false;
        }
        $padding = strlen($value) % 4;
        if($padding > 0)
        {
            $value .= str_repeat('=', 4-$padding);
        }
        return base64_decode(strtr($value, '-_', '+/'), true);
    }

    private static function NormalizePhone($value)
    {
        if(!is_string($value) && !is_int($value))
        {
            throw new InquiryPublicException('联系电话不能为空');
        }
        $value = self::NormalizeText((string) $value, '联系电话', 40, true, false);
        $value = str_replace([' ', '-', '(', ')', '（', '）'], '', $value);
        if(preg_match('/^\+?[0-9]{6,20}$/D', $value) !== 1)
        {
            throw new InquiryPublicException('联系电话格式无效');
        }
        return $value;
    }

    private static function NormalizeQuantity($value)
    {
        if(!is_string($value) && !is_int($value) && !is_float($value))
        {
            throw new InquiryPublicException('采购数量不能为空');
        }
        $value = trim((string) $value);
        if(preg_match('/^[0-9]{1,11}(?:\.[0-9]{1,3})?$/D', $value) !== 1)
        {
            throw new InquiryPublicException('采购数量必须是正十进制数，最多三位小数');
        }
        [$integer, $fraction] = array_pad(explode('.', $value, 2), 2, '');
        $integer = ltrim($integer, '0');
        $integer = ($integer === '') ? '0' : $integer;
        $fraction = str_pad($fraction, 3, '0');
        $normalized = $integer.'.'.$fraction;
        if($integer === '0' && intval($fraction) === 0)
        {
            throw new InquiryPublicException('采购数量必须大于零');
        }
        return $normalized;
    }

    private static function NormalizeMoney($value, $label, $required)
    {
        if($value === null || $value === '')
        {
            if($required)
            {
                throw new InquiryPublicException($label.'不能为空');
            }
            return null;
        }
        if(!is_string($value) && !is_int($value))
        {
            throw new InquiryPublicException($label.'格式无效');
        }
        $value = trim((string) $value);
        if(preg_match('/^[0-9]{1,10}(?:\.[0-9]{1,2})?$/D', $value) !== 1)
        {
            throw new InquiryPublicException($label.'必须是非负金额，最多两位小数');
        }
        [$integer, $fraction] = array_pad(explode('.', $value, 2), 2, '');
        $integer = ltrim($integer, '0');
        $integer = ($integer === '') ? '0' : $integer;
        $fraction = str_pad($fraction, 2, '0');
        return $integer.'.'.$fraction;
    }

    private static function NormalizeBoolean($value, $label)
    {
        if(is_bool($value))
        {
            return $value ? 1 : 0;
        }
        if(is_int($value) && ($value === 0 || $value === 1))
        {
            return $value;
        }
        if(is_string($value) && ($value === '0' || $value === '1'))
        {
            return intval($value);
        }
        throw new InquiryPublicException($label.'选项无效');
    }

    private static function NormalizeDate($value, $label, $nullable)
    {
        if($value === null || $value === '')
        {
            if($nullable)
            {
                return null;
            }
            throw new InquiryPublicException($label.'不能为空');
        }
        if(!is_string($value) || preg_match('/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/D', $value) !== 1)
        {
            throw new InquiryPublicException($label.'格式无效');
        }
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d', $value);
        $errors = \DateTimeImmutable::getLastErrors();
        if($date === false || (is_array($errors) && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) || $date->format('Y-m-d') !== $value)
        {
            throw new InquiryPublicException($label.'格式无效');
        }
        return $value;
    }

    private static function NormalizeText($value, $label, $max_length, $required, $allow_newlines)
    {
        if($value === null)
        {
            if($required)
            {
                throw new InquiryPublicException($label.'不能为空');
            }
            return '';
        }
        if(!is_string($value))
        {
            throw new InquiryPublicException($label.'格式无效');
        }
        if(!function_exists('mb_check_encoding') || !mb_check_encoding($value, 'UTF-8'))
        {
            throw new InquiryPublicException($label.'编码无效');
        }
        if(!class_exists('Normalizer'))
        {
            throw new InquiryPublicException('服务器缺少 Unicode 规范化能力');
        }
        $value = str_replace(["\r\n", "\r"], "\n", $value);
        $value = \Normalizer::normalize($value, \Normalizer::FORM_KC);
        if($value === false)
        {
            throw new InquiryPublicException($label.'编码无效');
        }
        $value = trim($value);
        if($value === '' && $required)
        {
            throw new InquiryPublicException($label.'不能为空');
        }
        if(!$allow_newlines)
        {
            $value = preg_replace('/[\r\n\t]+/u', ' ', $value);
        }
        if(preg_match('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', $value) === 1 || preg_match('/<\s*\/?\s*[a-zA-Z][^>]*>/u', $value) === 1)
        {
            throw new InquiryPublicException($label.'包含不允许的内容');
        }
        if(mb_strlen($value, 'UTF-8') > $max_length)
        {
            throw new InquiryPublicException($label.'长度超出限制');
        }
        return $value;
    }

    private static function NormalizeSnapshotText($value, $max_length)
    {
        if(!is_string($value))
        {
            $value = (string) $value;
        }
        if(!function_exists('mb_check_encoding') || !mb_check_encoding($value, 'UTF-8'))
        {
            throw new InquiryPublicException('商品快照编码无效');
        }
        if(class_exists('Normalizer'))
        {
            $normalized = \Normalizer::normalize($value, \Normalizer::FORM_KC);
            if($normalized !== false)
            {
                $value = $normalized;
            }
        }
        $value = trim(str_replace(["\r\n", "\r"], "\n", $value));
        if(mb_strlen($value, 'UTF-8') > $max_length)
        {
            throw new InquiryPublicException('商品快照字段长度超出限制');
        }
        return $value;
    }

    private static function StrictUnsignedId($value, $label)
    {
        if(is_int($value))
        {
            if($value <= 0 || $value > self::MAX_UINT32)
            {
                throw new InquiryPublicException($label.'无效');
            }
            return $value;
        }
        if(!is_string($value) || preg_match('/^[1-9][0-9]*$/D', $value) !== 1)
        {
            throw new InquiryPublicException($label.'无效');
        }
        if(strlen($value) > 10 || (strlen($value) === 10 && strcmp($value, (string) self::MAX_UINT32) > 0))
        {
            throw new InquiryPublicException($label.'无效');
        }
        return intval($value);
    }

    private static function StrictInquiryId($value)
    {
        if(is_int($value))
        {
            if($value <= 0)
            {
                throw new InquiryPublicException('询价编号无效');
            }
            return $value;
        }
        if(!is_string($value) || preg_match('/^[1-9][0-9]{0,18}$/D', $value) !== 1)
        {
            throw new InquiryPublicException('询价编号无效');
        }
        if(strlen($value) === 19 && strcmp($value, self::MAX_BIGINT) > 0)
        {
            throw new InquiryPublicException('询价编号无效');
        }
        return intval($value);
    }

    private static function StrictStatus($value)
    {
        if(!is_string($value) || !InquiryStateMachine::IsValid($value))
        {
            throw new InquiryPublicException('询价状态无效');
        }
        return $value;
    }

    private static function ValidStoredPrice($value, $label)
    {
        $normalized = ReferencePriceService::NormalizeInputPrice((string) $value);
        if($normalized === null || ReferencePriceService::StoredPriceToCents($normalized) < 1)
        {
            throw new InquiryPublicException($label.'无效');
        }
        return $normalized;
    }

    private static function DecodeJsonObject($value)
    {
        if(is_array($value))
        {
            return $value;
        }
        $decoded = json_decode((string) $value, true);
        return is_array($decoded) ? $decoded : [];
    }

    private static function PublicGoodsData($snapshot)
    {
        return [
            'id'              => $snapshot['goods_id'],
            'title'           => $snapshot['goods_title'],
            'images'          => $snapshot['goods_images'],
            'is_shelves'      => $snapshot['goods_status'],
            'inventory_unit'  => $snapshot['reference_unit'],
            'price'           => $snapshot['reference_price'],
            'reference_price' => [
                'text' => $snapshot['reference_price'],
                'short_text' => $snapshot['reference_price'].' / '.$snapshot['reference_unit'],
                'min'  => $snapshot['reference_min'],
                'max'  => $snapshot['reference_max'],
                'unit' => $snapshot['reference_unit'],
            ],
            'reference_price_text' => $snapshot['reference_price'].' / '.$snapshot['reference_unit'],
        ];
    }

    private static function PreferredUserName($profile)
    {
        if(!is_array($profile))
        {
            return '';
        }
        $name = trim((string) ($profile['nickname'] ?? ''));
        if($name === '')
        {
            $name = trim((string) ($profile['username'] ?? ''));
        }
        return self::NormalizeSnapshotText($name, 80);
    }

    private static function MaskPhone($phone)
    {
        $phone = (string) $phone;
        $length = strlen($phone);
        if($length < 7)
        {
            return str_repeat('*', $length);
        }
        return substr($phone, 0, 3).str_repeat('*', $length-7).substr($phone, -4);
    }

    private static function EscapeLike($value)
    {
        return str_replace(['\\', '%', '_'], ['\\\\', '\\%', '\\_'], (string) $value);
    }

    private static function PositivePage($value, $default)
    {
        if(is_int($value) && $value > 0)
        {
            return $value;
        }
        if(is_string($value) && preg_match('/^[1-9][0-9]{0,5}$/D', $value) === 1)
        {
            return intval($value);
        }
        return $default;
    }

    private static function PageData($items, $total, $page, $page_size)
    {
        $page_total = max(1, intval(ceil($total/$page_size)));
        return [
            'items'        => $items,
            'total'        => intval($total),
            'page'         => intval($page),
            'page_size'    => intval($page_size),
            'page_total'   => $page_total,
            'has_previous' => $page > 1,
            'previous_page'=> max(1, $page-1),
            'has_next'     => $page < $page_total,
            'next_page'    => min($page_total, $page+1),
        ];
    }

    private static function SafeRollback($connection)
    {
        if($connection !== null)
        {
            try {
                $connection->rollback();
            } catch(\Throwable $e) {
            }
        }
    }

    private static function IsDuplicateKeyError($error)
    {
        $code = (string) $error->getCode();
        $message = (string) $error->getMessage();
        return $code === '1062' || ($code === '23000' && strpos($message, '1062') !== false) || stripos($message, 'duplicate entry') !== false;
    }
}
?>
