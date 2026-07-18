<?php
namespace app\plugins\nursery\api;

use app\plugins\nursery\service\InquiryService;

class Inquiry
{
    private $user;

    public function __construct($params = [])
    {
        $this->user = isset($params['user']) && is_array($params['user']) ? $params['user'] : [];
    }

    public function Create($params = [])
    {
        return request()->isPost() ? InquiryService::Submit($this->user, $params) : DataReturn('询价写操作仅接受 POST 请求', -1);
    }

    public function List($params = [])
    {
        return InquiryService::UserList($this->user, $params);
    }

    public function Detail($params = [])
    {
        return InquiryService::UserDetail($this->user, $params);
    }
}
?>
