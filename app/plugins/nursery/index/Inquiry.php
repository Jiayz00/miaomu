<?php
namespace app\plugins\nursery\index;

use app\plugins\nursery\service\InquiryService;

class Inquiry
{
    private $user;

    public function __construct($params = [])
    {
        $this->user = isset($params['user']) && is_array($params['user']) ? $params['user'] : [];
    }

    public function Form($params = [])
    {
        IsUserLogin();
        $result = InquiryService::FormData($this->user, $params);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'inquiry_form'             => $result['data'],
            'form_data'                => $result['data'],
            'request_nonce'            => InquiryService::WebRequestNonce('user'),
            'nursery_inquiry_nonce'    => InquiryService::WebRequestNonce('user'),
            'nursery_inquiry_create_url' => PluginsHomeUrl('nursery', 'inquiry', 'create'),
        ]);
        return MyView('../../../plugins/nursery/view/index/inquiry/form');
    }

    public function Create($params = [])
    {
        IsUserLogin();
        $guard = InquiryService::ValidateWebWrite($params, 'user');
        if($guard['code'] !== 0)
        {
            return $guard;
        }
        $result = InquiryService::Submit($this->user, $params);
        if($result['code'] === 0 && !empty($result['data']['inquiry_id']))
        {
            $result['data']['detail_url'] = PluginsHomeUrl('nursery', 'inquiry', 'detail', ['id'=>$result['data']['inquiry_id']]);
        }
        return $result;
    }

    public function Index($params = [])
    {
        IsUserLogin();
        $result = InquiryService::UserList($this->user, $params);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'inquiry_list'  => $result['data'],
            'request_nonce' => InquiryService::WebRequestNonce('user'),
        ]);
        return MyView('../../../plugins/nursery/view/index/inquiry/index');
    }

    public function List($params = [])
    {
        IsUserLogin();
        return InquiryService::UserList($this->user, $params);
    }

    public function Detail($params = [])
    {
        IsUserLogin();
        $result = InquiryService::UserDetail($this->user, $params);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'inquiry_detail' => $result['data'],
            'request_nonce'  => InquiryService::WebRequestNonce('user'),
            'nursery_inquiry_nonce' => InquiryService::WebRequestNonce('user'),
        ]);
        return MyView('../../../plugins/nursery/view/index/inquiry/detail');
    }
}
?>
