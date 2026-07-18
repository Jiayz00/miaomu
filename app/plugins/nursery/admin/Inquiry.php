<?php
namespace app\plugins\nursery\admin;

use app\plugins\nursery\service\InquiryService;

class Inquiry
{
    private $admin;
    private $admin_plugins;

    public function __construct($params = [])
    {
        $this->admin = isset($params['admin']) && is_array($params['admin']) ? $params['admin'] : [];
        $this->admin_plugins = isset($params['admin_plugins']) && is_array($params['admin_plugins']) ? $params['admin_plugins'] : [];
    }

    public function Index($params = [])
    {
        $query = $params;
        if(isset($query['goods_keyword']) && !isset($query['goods']))
        {
            $query['goods'] = $query['goods_keyword'];
        }
        if(isset($query['phone']) && !isset($query['mobile']))
        {
            $query['mobile'] = $query['phone'];
        }
        if(isset($query['is_timeout']) && !isset($query['is_overdue']))
        {
            $query['is_overdue'] = $query['is_timeout'];
        }
        $result = InquiryService::AdminList($this->admin, $query);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'inquiry_list'        => $result['data'],
            'request_nonce'       => InquiryService::WebRequestNonce('admin'),
            'admin_action_power'  => $this->ActionPower(),
            'inquiry_actions'     => $this->ActionPower(),
            'status_options'      => \app\plugins\nursery\service\InquiryStateMachine::Labels(),
            'inquiry_filters'     => $params,
            'region_options'      => InquiryService::RegionOptions(),
            'admin_plugins'       => $this->admin_plugins,
        ]);
        return MyView('../../../plugins/nursery/view/admin/inquiry/index');
    }

    public function Detail($params = [])
    {
        $result = InquiryService::AdminDetail($this->admin, $params);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'inquiry_detail'     => $result['data'],
            'request_nonce'      => InquiryService::WebRequestNonce('admin'),
            'admin_action_power' => $this->ActionPower(),
            'inquiry_actions'   => $this->ActionPower(),
            'status_options'    => \app\plugins\nursery\service\InquiryStateMachine::Labels(),
            'region_options'    => InquiryService::RegionOptions(),
            'admin_plugins'     => $this->admin_plugins,
        ]);
        return MyView('../../../plugins/nursery/view/admin/inquiry/detail');
    }

    public function Reply($params = [])
    {
        $guard = InquiryService::ValidateWebWrite($params, 'admin');
        return ($guard['code'] === 0) ? InquiryService::AdminReply($this->admin, $params) : $guard;
    }

    public function StatusUpdate($params = [])
    {
        $guard = InquiryService::ValidateWebWrite($params, 'admin');
        return ($guard['code'] === 0) ? InquiryService::AdminStatusUpdate($this->admin, $params) : $guard;
    }

    public function ContactReveal($params = [])
    {
        $guard = InquiryService::ValidateWebWrite($params, 'admin');
        return ($guard['code'] === 0) ? InquiryService::AdminContactReveal($this->admin, $params) : $guard;
    }

    public function Reopen($params = [])
    {
        $guard = InquiryService::ValidateWebWrite($params, 'admin');
        return ($guard['code'] === 0) ? InquiryService::AdminReopen($this->admin, $params) : $guard;
    }

    private function ActionPower()
    {
        return [
            'index'         => AdminIsPower('inquiry', 'index', 'nursery'),
            'detail'        => AdminIsPower('inquiry', 'detail', 'nursery'),
            'reply'         => AdminIsPower('inquiry', 'reply', 'nursery'),
            'statusupdate'  => AdminIsPower('inquiry', 'statusupdate', 'nursery'),
            'contactreveal' => AdminIsPower('inquiry', 'contactreveal', 'nursery'),
            'reopen'        => AdminIsPower('inquiry', 'reopen', 'nursery'),
        ];
    }
}
?>
